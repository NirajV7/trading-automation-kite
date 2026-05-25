/**
 * Kite Quant Terminal - Electron Main Process
 * Controls native borderless desktop windows, hardware acceleration,
 * macOS system tray integration (P&L Ticker), and app lifecycle.
 */

const { app, BrowserWindow, Tray, Menu, ipcMain, shell } = require('electron');
const path = require('path');

let mainWindow = null;
let tray = null;

// Enforce hardware acceleration and smooth canvas rendering for TV charts
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-oop-rasterization');
app.commandLine.appendSwitch('enable-accelerated-video-decode');
app.commandLine.appendSwitch('gpu-renderer-creator');

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    frame: true, // Native window controls for standard OS handling
    titleBarStyle: 'hiddenInset', // Sleek integrated macOS titlebar style
    backgroundColor: '#0a0b0d', // Deep cyberpunk background to prevent flash
    show: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false, // Allows simple Alpine.js integration in renderer
      devTools: true
    }
  });

  // Redirect target="_blank" to external browser (prevents blank Electron login popup)
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Load the visual dashboard console
  const isDev = process.env.NODE_ENV === 'development';
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173').catch(() => {
      setTimeout(() => {
        mainWindow.loadURL('http://localhost:5173').catch(err => console.log("Failed to load dev URL:", err));
      }, 1000);
    });
  } else {
    mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'));
  }

  // Reveal window only when content is ready to prevent white screens
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createTray() {
  // Initialize native macOS system tray menu bar item
  // Fall back to a default label if no icon is specified
  tray = new Tray(path.join(__dirname, 'src', 'tray_placeholder.png'));
  
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Kite Quant Terminal', enabled: false },
    { type: 'separator' },
    { label: 'Show Console', click: () => { if (mainWindow) mainWindow.show(); } },
    { label: 'Minimize to Tray', click: () => { if (mainWindow) mainWindow.hide(); } },
    { type: 'separator' },
    { label: 'Panic Exit (All Trades)', click: () => {
        // Trigger emergency panic switch via IPC communication to renderer
        if (mainWindow) mainWindow.webContents.send('trigger-panic-kill');
      }
    },
    { type: 'separator' },
    { label: 'Quit App', click: () => { app.quit(); } }
  ]);

  tray.setToolTip('Kite Quant Terminal');
  tray.setContextMenu(contextMenu);
}

app.whenReady().then(() => {
  createWindow();
  
  // Try to create tray. If placeholder icon fails, log and continue
  try {
    createTray();
  } catch (e) {
    console.log("System tray initialization failed: " + e.message + "\n" + e.stack);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// IPC Handler to dynamically update the system tray P&L display in real-time
ipcMain.on('update-tray-pnl', (event, pnlText) => {
  if (tray) {
    tray.setTitle(pnlText);
  }
});
