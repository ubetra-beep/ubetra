package org.duckdns.ubeneeko.app;

import android.Manifest;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import androidx.core.app.NotificationManagerCompat;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

@CapacitorPlugin(
    name = "UbetraMedia",
    permissions = {
        @Permission(alias = "camera", strings = { Manifest.permission.CAMERA }),
        @Permission(alias = "microphone", strings = { Manifest.permission.RECORD_AUDIO })
    }
)
public class UbetraMediaPlugin extends Plugin {

  @PluginMethod
  public void checkPermissions(PluginCall call) {
    call.resolve(permissionStatus());
  }

  @PluginMethod
  public void requestPermissions(PluginCall call) {
    requestPermissionForAliases(new String[] { "camera", "microphone" }, call, "onPerms");
  }

  @PermissionCallback
  private void onPerms(PluginCall call) {
    call.resolve(permissionStatus());
  }

  private JSObject permissionStatus() {
    JSObject ret = new JSObject();
    ret.put("camera", getPermissionState("camera").toString());
    ret.put("microphone", getPermissionState("microphone").toString());
    boolean notes = NotificationManagerCompat.from(getContext()).areNotificationsEnabled();
    ret.put("notifications", notes ? "granted" : "denied");
    NotificationManager nm = getContext().getSystemService(NotificationManager.class);
    boolean dnd = Build.VERSION.SDK_INT < Build.VERSION_CODES.M
        || (nm != null && nm.isNotificationPolicyAccessGranted());
    ret.put("dnd", dnd ? "granted" : "prompt");
    return ret;
  }

  @PluginMethod
  public void openAppSettings(PluginCall call) {
    Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
    intent.setData(Uri.parse("package:" + getContext().getPackageName()));
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    getContext().startActivity(intent);
    call.resolve();
  }

  @PluginMethod
  public void openNotificationSettings(PluginCall call) {
    Intent intent;
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      intent = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
      intent.putExtra(Settings.EXTRA_APP_PACKAGE, getContext().getPackageName());
    } else {
      intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
      intent.setData(Uri.parse("package:" + getContext().getPackageName()));
    }
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    getContext().startActivity(intent);
    call.resolve();
  }

  @PluginMethod
  public void openDndSettings(PluginCall call) {
    Intent intent = new Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS);
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    getContext().startActivity(intent);
    call.resolve();
  }

  @PluginMethod
  public void openBatterySettings(PluginCall call) {
    try {
      Intent intent = new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
      intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
      getContext().startActivity(intent);
      call.resolve();
    } catch (Exception e) {
      openAppSettings(call);
    }
  }

  @PluginMethod
  public void setTorch(PluginCall call) {
    boolean on = Boolean.TRUE.equals(call.getBoolean("on", false));
    Double levelObj = call.getDouble("level");
    double level = levelObj == null ? (on ? 1.0 : 0.0) : levelObj;
    try {
      CameraManager cm = (CameraManager) getContext().getSystemService(Context.CAMERA_SERVICE);
      if (cm == null) {
        call.reject("No camera manager");
        return;
      }
      String torchId = null;
      Integer maxStrength = null;
      for (String id : cm.getCameraIdList()) {
        CameraCharacteristics chars = cm.getCameraCharacteristics(id);
        Boolean flash = chars.get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
        if (!Boolean.TRUE.equals(flash)) continue;
        Integer facing = chars.get(CameraCharacteristics.LENS_FACING);
        torchId = id;
        if (Build.VERSION.SDK_INT >= 33) {
          try {
            Object key = CameraCharacteristics.class.getField("FLASH_INFO_STRENGTH_MAXIMUM_LEVEL").get(null);
            Object value = chars.get((android.hardware.camera2.CameraCharacteristics.Key<?>) key);
            if (value instanceof Integer) maxStrength = (Integer) value;
          } catch (Exception ignored) {
            maxStrength = null;
          }
        }
        if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK) {
          break;
        }
      }
      if (torchId == null) {
        call.reject("No flashlight on this phone");
        return;
      }
      boolean dimSupported = maxStrength != null && maxStrength > 1;
      if (!on || level <= 0) {
        cm.setTorchMode(torchId, false);
      } else {
        if (Build.VERSION.SDK_INT >= 33 && dimSupported) {
          int strength = Math.max(1, (int) Math.round(level * maxStrength));
          if (strength > maxStrength) strength = maxStrength;
          try {
            CameraManager.class
                .getMethod("setTorchStrengthLevel", String.class, int.class)
                .invoke(cm, torchId, strength);
          } catch (Exception ignored) {
            /* older compile SDK — on/off still works */
          }
        }
        cm.setTorchMode(torchId, true);
      }
      JSObject ret = new JSObject();
      ret.put("on", on && level > 0);
      ret.put("level", level);
      ret.put("dimSupported", dimSupported);
      call.resolve(ret);
    } catch (Exception e) {
      call.reject(e.getMessage() == null ? "Torch failed" : e.getMessage());
    }
  }
}
