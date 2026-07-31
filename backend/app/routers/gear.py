from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, GearInventoryItem, User
from ..schemas import (
    GearBundleOut,
    GearCatalogItemOut,
    GearCategoryOut,
    GearInventoryItemOut,
    GearInventoryUpdate,
    GearInventoryUpsert,
)
from ..services.features import is_feature_enabled
from ..services.gear_catalog import catalog_categories, catalog_item_by_id, catalog_items

router = APIRouter(prefix="/dynamics", tags=["gear"])

VALID_CATEGORIES = {"vanilla_toys", "kinky_stuff", "outfits"}


def _item_out(item: GearInventoryItem) -> GearInventoryItemOut:
    return GearInventoryItemOut(
        id=item.id,
        catalog_item_id=item.catalog_item_id,
        category=item.category,
        name=item.name,
        notes=item.notes or "",
        owned=bool(item.owned),
        want=bool(item.want),
        is_custom=bool(item.is_custom),
        tier=item.tier or "common",
        created_at=item.created_at,
    )


@router.get("/{dynamic_id}/gear", response_model=GearBundleOut)
def get_gear(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    category: str | None = None,
) -> GearBundleOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if not is_feature_enabled(dynamic, "gear"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gear is disabled for this dynamic")

    inventory = (
        db.query(GearInventoryItem)
        .filter(GearInventoryItem.dynamic_id == dynamic_id)
        .order_by(GearInventoryItem.name)
        .all()
    )
    by_catalog = {
        item.catalog_item_id: item for item in inventory if item.catalog_item_id
    }

    catalog_out: list[GearCatalogItemOut] = []
    for entry in catalog_items(category):
        inv = by_catalog.get(entry["id"])
        catalog_out.append(
            GearCatalogItemOut(
                id=entry["id"],
                category=entry["category"],
                name=entry["name"],
                notes=entry.get("notes") or "",
                tier=entry.get("tier") or "common",
                owned=bool(inv.owned) if inv else False,
                want=bool(inv.want) if inv else False,
                inventory_id=inv.id if inv else None,
            )
        )

    inv_out = [_item_out(item) for item in inventory]
    if category:
        inv_out = [item for item in inv_out if item.category == category]

    return GearBundleOut(
        categories=[
            GearCategoryOut(
                id=cat["id"],
                label=cat["label"],
                description=cat.get("description") or "",
            )
            for cat in catalog_categories()
        ],
        catalog=catalog_out,
        inventory=inv_out,
        owned_count=sum(1 for item in inventory if item.owned),
        want_count=sum(1 for item in inventory if item.want),
    )


@router.post(
    "/{dynamic_id}/gear",
    response_model=GearInventoryItemOut,
    status_code=status.HTTP_201_CREATED,
)
def upsert_gear_item(
    dynamic_id: str,
    payload: GearInventoryUpsert,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GearInventoryItemOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if not is_feature_enabled(dynamic, "gear"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gear is disabled for this dynamic")

    if payload.catalog_item_id:
        catalog = catalog_item_by_id(payload.catalog_item_id)
        if catalog is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog item not found")
        existing = (
            db.query(GearInventoryItem)
            .filter(
                GearInventoryItem.dynamic_id == dynamic_id,
                GearInventoryItem.catalog_item_id == payload.catalog_item_id,
            )
            .first()
        )
        if existing:
            existing.owned = payload.owned
            existing.want = payload.want
            if payload.notes is not None:
                existing.notes = payload.notes.strip()
            if not existing.owned and not existing.want:
                db.delete(existing)
                db.commit()
                return GearInventoryItemOut(
                    id=existing.id,
                    catalog_item_id=existing.catalog_item_id,
                    category=existing.category,
                    name=existing.name,
                    notes=existing.notes or "",
                    owned=False,
                    want=False,
                    is_custom=False,
                    tier=existing.tier or "common",
                    created_at=existing.created_at,
                )
            db.commit()
            db.refresh(existing)
            return _item_out(existing)

        if not payload.owned and not payload.want:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mark owned or want to add a catalog item",
            )
        item = GearInventoryItem(
            dynamic_id=dynamic_id,
            catalog_item_id=catalog["id"],
            category=catalog["category"],
            name=catalog["name"],
            notes=(payload.notes or catalog.get("notes") or "").strip(),
            owned=payload.owned,
            want=payload.want,
            is_custom=False,
            tier=catalog.get("tier") or "common",
            added_by_membership_id=membership.id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return _item_out(item)

    name = (payload.name or "").strip()
    category = (payload.category or "kinky_stuff").strip()
    if category not in VALID_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required")
    item = GearInventoryItem(
        dynamic_id=dynamic_id,
        catalog_item_id=None,
        category=category,
        name=name,
        notes=(payload.notes or "").strip(),
        owned=payload.owned,
        want=payload.want,
        is_custom=True,
        tier="custom",
        added_by_membership_id=membership.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.patch("/{dynamic_id}/gear/{item_id}", response_model=GearInventoryItemOut)
def update_gear_item(
    dynamic_id: str,
    item_id: str,
    payload: GearInventoryUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GearInventoryItemOut:
    get_membership(dynamic_id, user, db)
    item = (
        db.query(GearInventoryItem)
        .filter(GearInventoryItem.id == item_id, GearInventoryItem.dynamic_id == dynamic_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gear item not found")
    if payload.name is not None and item.is_custom:
        item.name = payload.name.strip() or item.name
    if payload.notes is not None:
        item.notes = payload.notes.strip()
    if payload.owned is not None:
        item.owned = payload.owned
    if payload.want is not None:
        item.want = payload.want
    if payload.category is not None and payload.category in VALID_CATEGORIES and item.is_custom:
        item.category = payload.category
    if not item.owned and not item.want and not item.is_custom:
        db.delete(item)
        db.commit()
        return _item_out(item)
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.delete(
    "/{dynamic_id}/gear/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_gear_item(
    dynamic_id: str,
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    get_membership(dynamic_id, user, db)
    item = (
        db.query(GearInventoryItem)
        .filter(GearInventoryItem.id == item_id, GearInventoryItem.dynamic_id == dynamic_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gear item not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
