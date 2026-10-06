const { registerPlugin } = require("@capacitor/core");

const UbetraAppUpdater = registerPlugin("UbetraAppUpdater", {
  web: () => ({
    canInstall: async () => ({ canInstall: false }),
    openInstallPermission: async () => ({ canInstall: false }),
    downloadAndInstall: async () => ({ installed: false }),
  }),
});

module.exports = { UbetraAppUpdater };
