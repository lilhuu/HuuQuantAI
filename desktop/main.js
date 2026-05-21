const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn, execFile } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

let mainWindow = null;
let backendProcess = null;
let backendUrl = null;
let backendPort = null;
let isQuitting = false;

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
  process.exit(0);
}

app.on("second-instance", () => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
});

function getUserDataDir() {
  return path.join(app.getPath("appData"), "HuuQuantAI");
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function getLogDir() {
  const logDir = path.join(getUserDataDir(), "logs");
  ensureDir(logDir);
  return logDir;
}

function appendDesktopLog(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  fs.appendFileSync(path.join(getLogDir(), "desktop.log"), line, "utf8");
}

function getBackendExecutable() {
  if (process.env.AUTO_TRADER_BACKEND_EXE) {
    return process.env.AUTO_TRADER_BACKEND_EXE;
  }

  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend", "auto_trader_backend.exe");
  }

  return path.join(__dirname, "..", "dist", "desktop-backend", "auto_trader_backend.exe");
}

function getSourcePythonFallback() {
  const root = path.join(__dirname, "..");
  const venvPython = path.join(root, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvPython)) {
    return { command: venvPython, args: [path.join(root, "desktop_backend.py")], cwd: root };
  }
  return { command: "python", args: [path.join(root, "desktop_backend.py")], cwd: root };
}

function findFreePort(host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = address.port;
      server.close(() => resolve(port));
    });
  });
}

function requestJson(url, timeoutMs = 1200) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`HTTP ${response.statusCode}: ${body.slice(0, 200)}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    request.on("timeout", () => {
      request.destroy(new Error("request timeout"));
    });
    request.on("error", reject);
  });
}

async function waitForBackend(url, timeoutMs = 30000) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    try {
      await requestJson(`${url}/healthz`);
      return;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 450));
    }
  }
  throw new Error(`交易内核启动超时：${lastError ? lastError.message : "unknown error"}`);
}

function sendStatus(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("desktop-status", payload);
  }
}

async function startBackend() {
  if (backendProcess && backendUrl) {
    return backendUrl;
  }

  backendPort = await findFreePort();
  backendUrl = `http://127.0.0.1:${backendPort}`;

  const logDir = getLogDir();
  const stdout = fs.openSync(path.join(logDir, "backend.stdout.log"), "a");
  const stderr = fs.openSync(path.join(logDir, "backend.stderr.log"), "a");
  const backendExe = getBackendExecutable();
  const appDataDir = getUserDataDir();
  ensureDir(appDataDir);

  const env = {
    ...process.env,
    AUTO_TRADER_DESKTOP: "1",
    AUTO_TRADER_HOST: "127.0.0.1",
    AUTO_TRADER_PORT: String(backendPort),
    AUTO_TRADER_APP_DATA_DIR: appDataDir,
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  };

  let command = backendExe;
  let args = [];
  let cwd = path.dirname(backendExe);

  if (!fs.existsSync(backendExe)) {
    const fallback = getSourcePythonFallback();
    command = fallback.command;
    args = fallback.args;
    cwd = fallback.cwd;
    appendDesktopLog(`Backend exe missing, using Python fallback: ${command} ${args.join(" ")}`);
  } else {
    appendDesktopLog(`Starting backend exe: ${backendExe}`);
  }

  backendProcess = spawn(command, args, {
    cwd,
    env,
    windowsHide: true,
    stdio: ["ignore", stdout, stderr],
  });

  backendProcess.on("exit", (code, signal) => {
    appendDesktopLog(`Backend exited code=${code} signal=${signal}`);
    backendProcess = null;
    if (!isQuitting) {
      sendStatus({
        type: "backend-exit",
        message: "交易内核已退出，请重试启动。",
        code,
        signal,
      });
    }
  });

  backendProcess.on("error", (error) => {
    appendDesktopLog(`Backend spawn error: ${error.stack || error.message}`);
    sendStatus({
      type: "backend-error",
      message: error.message,
    });
  });

  sendStatus({ type: "starting", message: "正在启动交易内核..." });
  await waitForBackend(backendUrl);
  appendDesktopLog(`Backend ready: ${backendUrl}`);
  return backendUrl;
}

function stopBackend() {
  if (!backendProcess) {
    return;
  }

  const pid = backendProcess.pid;
  appendDesktopLog(`Stopping backend pid=${pid}`);
  try {
    backendProcess.kill();
  } catch (error) {
    appendDesktopLog(`Backend kill failed: ${error.message}`);
  }

  if (process.platform === "win32" && pid) {
    setTimeout(() => {
      execFile("taskkill", ["/PID", String(pid), "/T", "/F"], () => {});
    }, 1200);
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 760,
    minHeight: 640,
    backgroundColor: "#061520",
    title: "HUU Auto Trade Console",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "loading.html"));

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://127.0.0.1:") || url.startsWith("http://localhost:")) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (url.startsWith("file://") || (backendUrl && url.startsWith(backendUrl))) {
      return;
    }
    event.preventDefault();
  });
}

async function bootDesktopApp() {
  try {
    createWindow();
    const url = await startBackend();
    sendStatus({ type: "ready", message: "交易内核已就绪。", url });
    await mainWindow.loadURL(url);
  } catch (error) {
    appendDesktopLog(`Desktop boot failed: ${error.stack || error.message}`);
    sendStatus({
      type: "failed",
      message: error.message || "桌面应用启动失败",
    });
  }
}

ipcMain.handle("retry-backend", async () => {
  stopBackend();
  backendProcess = null;
  backendUrl = null;
  await mainWindow.loadFile(path.join(__dirname, "loading.html"));
  const url = await startBackend();
  await mainWindow.loadURL(url);
  return { ok: true, url };
});

ipcMain.handle("open-logs", async () => {
  shell.openPath(getLogDir());
  return { ok: true };
});

app.setName("HUU Auto Trade Console");
app.setPath("userData", getUserDataDir());

app.whenReady().then(bootDesktopApp);

app.on("before-quit", () => {
  isQuitting = true;
  stopBackend();
});

app.on("window-all-closed", () => {
  isQuitting = true;
  stopBackend();
  app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    bootDesktopApp();
  }
});
