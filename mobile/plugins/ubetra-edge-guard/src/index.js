const { registerPlugin } = require("@capacitor/core");

const UbetraEdgeGuard = registerPlugin("UbetraEdgeGuard", {
  web: () => ({
    getStatus: async () => ({
      available: false,
      enabled: false,
      running: false,
      vpnPermissionGranted: false,
      domainCount: 0,
      domains: [],
    }),
    requestVpnPermission: async () => ({ granted: false }),
    setEnabled: async () => ({ enabled: false, running: false }),
    getBlockedDomains: async () => ({ domains: [] }),
    setBlockedDomains: async () => ({ domains: [] }),
    addBlockedDomain: async () => ({ domains: [] }),
    removeBlockedDomain: async () => ({ domains: [] }),
  }),
});

module.exports = { UbetraEdgeGuard };
