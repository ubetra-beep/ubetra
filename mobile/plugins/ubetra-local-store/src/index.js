const { registerPlugin } = require("@capacitor/core");

const UbetraLocalStore = registerPlugin("UbetraLocalStore", {
  web: () => ({
    getServerConfig: async () => ({
      serverUrl: "",
      phoneOnly: false,
      choiceMade: false,
      serverConfigured: false,
      serverReachable: false,
      lastSyncAt: "",
      pendingCount: 0,
      localLoggerReady: false,
    }),
    getStatus: async () => ({ localLoggerReady: false }),
    listRecent: async () => ({ entries: [] }),
    logOrgasm: async () => { throw new Error("Local log is in the Android app"); },
    chastityAction: async () => { throw new Error("Local log is in the Android app"); },
    enqueueSync: async () => ({ started: false }),
    syncNow: async () => ({ ok: false }),
    probeServer: async () => ({ reachable: false }),
    setServerUrl: async () => ({ ok: false }),
    setPhoneOnly: async () => ({ ok: false }),
    setSession: async () => ({ ok: true }),
    startWatchPairing: async () => { throw new Error("Pair the watch from the Android app"); },
    watchStatus: async () => ({ paired: false }),
    forgetWatch: async () => ({ ok: true }),
    showServerSetup: async () => ({ ok: false }),
  }),
});

module.exports = { UbetraLocalStore };
