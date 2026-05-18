const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopApi", {
  retryBackend: () => ipcRenderer.invoke("retry-backend"),
  openLogs: () => ipcRenderer.invoke("open-logs"),
  onStatus: (callback) => {
    ipcRenderer.on("desktop-status", (_event, payload) => callback(payload));
  },
});
