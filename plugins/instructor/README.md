# Instructor plugin

Playtime Instructor is a UBETRA-hosted game adapted from
[rororosi/fapinstructor-client](https://github.com/rororosi/fapinstructor-client)
(fork of EroticRide / Fap Instructor; GPL-2.0). The upstream CRA/Auth0/Sentry app
is **not** vendored. The in-app engine lives in `frontend/instructor.js` and talks
only to UBETRA HTTP APIs. Overlay HUD, task packs, and create-game settings follow
the hosted legacy client at fapinstructor.com (local files only; no Scrolller).

License: [LICENSE.txt](LICENSE.txt)

Media is **not** fetched from RedGIFs in this process. Point `UBETRA_REDGIFS_HOST` at a local folder of playlists (subdirectories). UBETRA bind-mounts that tree read-only.
