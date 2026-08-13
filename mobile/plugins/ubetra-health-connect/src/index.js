const { registerPlugin } = require("@capacitor/core");

const UbetraHealthConnect = registerPlugin("UbetraHealthConnect", {
  web: () => ({
    checkAvailability: async () => ({ availability: "NotSupported" }),
    requestAccess: async () => ({ granted: false }),
    exportSleep: async () => ({ sessions: [] }),
    exportCycle: async () => ({ days: [] }),
  }),
});

module.exports = { UbetraHealthConnect };
