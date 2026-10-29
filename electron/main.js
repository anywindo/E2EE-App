const { app, BrowserWindow, ipcMain, shell, Menu, nativeImage } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const os = require('os');

let mainWindow = null;
let activeApp = 'app'; // 'app' or 'chat'
let isQuitting = false;

const projectRoot = path.resolve(__dirname, '..');

// Services definition: both run simultaneously and stay alive
const services = {
  app: {
    name: 'Benchmark & Analysis',
    script: 'app.py',
    port: 7860,
    process: null,
    status: { status: 'starting', app: 'app', port: 7860, url: null, message: 'Starting app.py on port 7860...' },
    url: null
  },
  chat: {
    name: 'E2EE Chat Demo',
    script: 'chat_demo.py',
    port: 7861,
    process: null,
    status: { status: 'starting', app: 'chat', port: 7861, url: null, message: 'Starting chat_demo.py on port 7861...' },
    url: null
  }
};

function killPortProcess(port) {
  try {
    if (process.platform === 'win32') {
      const out = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      const lines = out.trim().split('\n');
      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        const pid = parts[parts.length - 1];
        if (pid && !isNaN(pid) && pid !== '0') {
          spawn('taskkill', ['/pid', pid, '/f', '/t']);
        }
      }
    } else {
      const pids = execSync(`lsof -ti :${port}`, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
      if (pids) {
        for (const pid of pids.split('\n')) {
          if (pid && !isNaN(pid)) {
            try {
              process.kill(parseInt(pid, 10), 'SIGKILL');
            } catch (e) { }
          }
        }
      }
    }
  } catch (e) {
    // Port was free or command completed
  }
}

function getPythonExecutable() {
  const isWin = process.platform === 'win32';
  const venvPythonWin = path.join(projectRoot, 'venv', 'Scripts', 'python.exe');
  const venvPythonUnix = path.join(projectRoot, 'venv', 'bin', 'python');

  if (isWin && fs.existsSync(venvPythonWin)) {
    return venvPythonWin;
  }
  if (!isWin && fs.existsSync(venvPythonUnix)) {
    return venvPythonUnix;
  }

  return isWin ? 'python' : 'python3';
}

function getBackendExecution(appKey) {
  const isWin = process.platform === 'win32';
  const targetName = appKey === 'app' ? 'app_backend' : 'chat_backend';
  const exeSuffix = isWin ? '.exe' : '';

  // Check packaged location in process.resourcesPath/bin
  if (app.isPackaged) {
    const candidateDirs = [
      path.join(process.resourcesPath, 'bin', targetName, `${targetName}${exeSuffix}`),
      path.join(process.resourcesPath, 'bin', `${targetName}${exeSuffix}`),
      path.join(process.resourcesPath, targetName, `${targetName}${exeSuffix}`)
    ];

    for (const cand of candidateDirs) {
      if (fs.existsSync(cand)) {
        return {
          command: cand,
          args: [],
          cwd: path.dirname(cand),
          isPackaged: true
        };
      }
    }
  }

  // Development / fallback: run script with Python interpreter
  const pythonPath = getPythonExecutable();
  const scriptPath = path.join(projectRoot, services[appKey].script);
  return {
    command: pythonPath,
    args: [scriptPath],
    cwd: projectRoot,
    isPackaged: false
  };
}

function sendToWindow(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data);
  }
}

function updateServiceStatus(appKey, statusData) {
  const s = services[appKey];
  if (!s) return;
  s.status = { ...s.status, ...statusData, app: appKey, port: s.port };
  if (statusData.url) {
    s.url = statusData.url;
  }
  console.log(`[E2EE Suite Status ${appKey.toUpperCase()}] ${statusData.status.toUpperCase()}: ${statusData.message || ''}`);
  sendToWindow('backend-status', s.status);
}

function checkServerReady(port, retries = 180, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const intervalId = setInterval(() => {
      attempts++;
      const req = http.get(`http://127.0.0.1:${port}`, (res) => {
        clearInterval(intervalId);
        resolve(`http://127.0.0.1:${port}`);
      });

      req.on('error', () => {
        if (attempts >= retries) {
          clearInterval(intervalId);
          reject(new Error(`Timed out waiting for backend on port ${port}`));
        }
      });

      req.setTimeout(400, () => {
        req.destroy();
      });
    }, interval);
  });
}

function startService(appKey) {
  const s = services[appKey];
  if (!s) return;

  if (s.process && !s.process.killed) {
    console.log(`[Tugas Akhir] Service ${appKey} is already running.`);
    checkServerReady(s.port, 15, 300).then((url) => {
      updateServiceStatus(appKey, {
        status: 'ready',
        url,
        message: `${s.script} is ready on port ${s.port}!`
      });
    }).catch(() => {});
    return;
  }

  killPortProcess(s.port);
  const backend = getBackendExecution(appKey);

  updateServiceStatus(appKey, {
    status: 'starting',
    script: s.script,
    port: s.port,
    message: `Launching ${s.script} on port ${s.port}...`
  });

  const userCacheDir = process.platform === 'win32'
    ? path.join(process.env.LOCALAPPDATA || os.homedir(), 'E2EESuite', 'matplotlib')
    : path.join(os.homedir(), '.cache', 'e2ee_suite_matplotlib');
  fs.mkdirSync(userCacheDir, { recursive: true });

  const env = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    GRADIO_SERVER_PORT: s.port.toString(),
    GRADIO_SERVER_NAME: '127.0.0.1',
    MPLCONFIGDIR: userCacheDir
  };

  try {
    const proc = spawn(backend.command, backend.args, {
      cwd: backend.cwd,
      env,
      detached: process.platform !== 'win32'
    });
    s.process = proc;

    sendToWindow('backend-log', {
      app: appKey,
      text: `[Tugas Akhir Process] Started ${s.script} (PID: ${proc.pid}) on port ${s.port}\n`
    });

    proc.stdout.on('data', (chunk) => {
      sendToWindow('backend-log', { app: appKey, text: chunk.toString() });
    });

    proc.stderr.on('data', (chunk) => {
      sendToWindow('backend-log', { app: appKey, text: chunk.toString() });
    });

    proc.on('error', (err) => {
      sendToWindow('backend-log', { app: appKey, text: `[Tugas Akhir Error] ${s.script}: ${err.message}\n` });
      updateServiceStatus(appKey, {
        status: 'error',
        message: `Failed to launch ${s.script}: ${err.message}`
      });
    });

    proc.on('exit', (code, signal) => {
      sendToWindow('backend-log', { app: appKey, text: `[Tugas Akhir Process] ${s.script} exited with code ${code} (${signal || 'clean'})\n` });
      if (s.process === proc) {
        s.process = null;
        updateServiceStatus(appKey, {
          status: 'stopped',
          message: `${s.script} stopped (code ${code})`
        });
      }
    });

    checkServerReady(s.port).then((url) => {
      updateServiceStatus(appKey, {
        status: 'ready',
        url,
        message: `${s.script} is ready on port ${s.port}!`
      });
    }).catch((err) => {
      updateServiceStatus(appKey, {
        status: 'error',
        message: err.message
      });
    });
  } catch (err) {
    updateServiceStatus(appKey, {
      status: 'error',
      message: `Failed to start ${s.script}: ${err.message}`
    });
  }
}

function stopService(appKey) {
  const s = services[appKey];
  if (!s || !s.process) return Promise.resolve();

  const proc = s.process;
  s.process = null;
  updateServiceStatus(appKey, { status: 'stopping', message: `Stopping ${s.script}...` });

  return new Promise((resolve) => {
    let resolved = false;
    const finish = () => {
      if (!resolved) {
        resolved = true;
        resolve();
      }
    };
    proc.once('exit', finish);

    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', proc.pid.toString(), '/f', '/t']);
      } else {
        try {
          process.kill(-proc.pid, 'SIGTERM');
        } catch (e) {
          proc.kill('SIGTERM');
        }
      }
    } catch (e) { }

    setTimeout(() => {
      try {
        if (!proc.killed) {
          if (process.platform === 'win32') {
            spawn('taskkill', ['/pid', proc.pid.toString(), '/f', '/t']);
          } else {
            try {
              process.kill(-proc.pid, 'SIGKILL');
            } catch (e) {
              proc.kill('SIGKILL');
            }
          }
        }
      } catch (e) { }
      finish();
    }, 2000);
  });
}

async function stopAllServices() {
  await Promise.all([stopService('app'), stopService('chat')]);
  killPortProcess(7860);
  killPortProcess(7861);
}

function getServicesSummary() {
  return {
    app: {
      name: services.app.name,
      script: services.app.script,
      port: services.app.port,
      url: services.app.url,
      isRunning: Boolean(services.app.process),
      status: services.app.status
    },
    chat: {
      name: services.chat.name,
      script: services.chat.script,
      port: services.chat.port,
      url: services.chat.url,
      isRunning: Boolean(services.chat.process),
      status: services.chat.status
    }
  };
}

function createWindow() {
  const isMac = process.platform === 'darwin';
  const iconPath = path.join(projectRoot, 'assets', isMac ? 'icon.icns' : 'icon.ico');

  mainWindow = new BrowserWindow({
    width: 1420,
    height: 940,
    minWidth: 1040,
    minHeight: 700,
    title: 'E2EE Suite',
    icon: fs.existsSync(iconPath) ? iconPath : path.join(projectRoot, 'assets', 'appIcon.png'),
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 18, y: 17 } : undefined,
    vibrancy: isMac ? 'under-window' : undefined,
    visualEffectState: isMac ? 'active' : undefined,
    backgroundColor: isMac ? '#00000000' : '#18181b',
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      webviewTag: true,
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  mainWindow.webContents.on('did-finish-load', () => {
    sendToWindow('initial-state', {
      activeApp,
      services: getServicesSummary()
    });
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  setupMenu();

  // Launch BOTH services concurrently so both stay alive!
  console.log('[Tugas Akhir] Launching both backends (app.py :7860 and chat_demo.py :7861)...');
  startService('app');
  startService('chat');
}

function setupMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    }] : []),
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'pasteAndMatchStyle' },
        { role: 'delete' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'Switch Application',
      submenu: [
        {
          label: 'Benchmark & Analysis Suite (app.py)',
          accelerator: 'CmdOrCtrl+1',
          click: () => {
            activeApp = 'app';
            sendToWindow('switch-tab', 'app');
          }
        },
        {
          label: 'E2EE Chat Demo (chat_demo.py)',
          accelerator: 'CmdOrCtrl+2',
          click: () => {
            activeApp = 'chat';
            sendToWindow('switch-tab', 'chat');
          }
        },
        { type: 'separator' },
        {
          label: 'Restart Current Backend',
          accelerator: 'CmdOrCtrl+Shift+R',
          click: async () => {
            await stopService(activeApp);
            startService(activeApp);
          }
        },
        {
          label: 'Restart Both Backends',
          click: async () => {
            await stopAllServices();
            startService('app');
            startService('chat');
          }
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        ...(isMac ? [
          { type: 'separator' },
          { role: 'front' },
          { type: 'separator' },
          { role: 'window' }
        ] : [
          { role: 'close' }
        ])
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

// IPC Handlers
ipcMain.handle('set-active-app', (event, appKey) => {
  activeApp = appKey;
  return { activeApp, services: getServicesSummary() };
});

ipcMain.handle('switch-app', (event, appKey) => {
  activeApp = appKey;
  return { activeApp, services: getServicesSummary() };
});

ipcMain.handle('restart-backend', async (event, targetApp) => {
  const appToRestart = targetApp || activeApp;
  await stopService(appToRestart);
  startService(appToRestart);
  return getServicesSummary();
});

ipcMain.handle('open-external', async (event, url) => {
  if (url) {
    shell.openExternal(url);
  } else {
    const s = services[activeApp];
    shell.openExternal(s ? s.url : 'http://127.0.0.1:7860');
  }
});

ipcMain.handle('get-state', () => {
  return {
    activeApp,
    services: getServicesSummary(),
    pythonPath: getPythonExecutable()
  };
});

// Clean shutdown
app.on('before-quit', async (e) => {
  if (!isQuitting) {
    e.preventDefault();
    isQuitting = true;
    await stopAllServices();
    app.quit();
  }
});

app.on('window-all-closed', async () => {
  await stopAllServices();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// Enable right-click context menu (Copy, Cut, Paste, Select All) for all webContents (windows and webviews)
app.on('web-contents-created', (event, contents) => {
  contents.on('context-menu', (e, params) => {
    const menuTemplate = [];

    if (params.selectionText && params.selectionText.trim().length > 0) {
      menuTemplate.push(
        { role: 'copy' },
        { type: 'separator' },
        { role: 'selectAll' }
      );
    } else if (params.isEditable) {
      menuTemplate.push(
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { type: 'separator' },
        { role: 'selectAll' }
      );
    } else {
      menuTemplate.push(
        { role: 'copy' },
        { role: 'selectAll' }
      );
    }

    if (menuTemplate.length > 0) {
      const contextMenu = Menu.buildFromTemplate(menuTemplate);
      contextMenu.popup();
    }
  });
});

app.setName('E2EE Suite');

function setDockIcon() {
  if (process.platform === 'darwin' && app.dock) {
    const pngIconPath = path.join(projectRoot, 'assets', 'appIcon.png');
    const dockIconPath = path.join(projectRoot, 'assets', 'icon.icns');
    try {
      if (fs.existsSync(pngIconPath)) {
        const image = nativeImage.createFromPath(pngIconPath);
        if (!image.isEmpty()) {
          app.dock.setIcon(image);
          return;
        }
      }
      if (fs.existsSync(dockIconPath)) {
        app.dock.setIcon(dockIconPath);
      }
    } catch (err) {
      console.error('[E2EE Suite] Failed to set dock icon:', err);
    }
  }
}

app.whenReady().then(() => {
  setDockIcon();
  createWindow();
});

// Handle CLI termination signals
const handleExit = async () => {
  await stopAllServices();
  process.exit(0);
};

process.on('SIGINT', handleExit);
process.on('SIGTERM', handleExit);
process.on('exit', () => {
  for (const key of Object.keys(services)) {
    const proc = services[key].process;
    if (proc) {
      try {
        if (process.platform === 'win32') {
          spawn('taskkill', ['/pid', proc.pid.toString(), '/f', '/t']);
        } else {
          process.kill(-proc.pid, 'SIGKILL');
        }
      } catch (e) { }
    }
  }
});
