const childProcess = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const root = path.resolve(__dirname, "..");
const logs = path.join(root, "logs");
const stopConflicts = process.argv.includes("--stop-port-conflicts") || process.argv.includes("-StopPortConflicts");
fs.mkdirSync(logs, { recursive: true });

function run(command, args, options = {}) {
  return childProcess.spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    stdio: options.stdio || "pipe",
    windowsHide: true,
  });
}

function ps(script) {
  const result = run("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]);
  return result.stdout.trim();
}

function listener(port) {
  const output = ps(
    `Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 LocalPort,OwningProcess | ConvertTo-Json -Compress`,
  );
  if (!output) return null;
  try {
    return JSON.parse(output);
  } catch {
    return null;
  }
}

function commandLine(pid) {
  if (!pid) return "";
  return ps(`(Get-CimInstance Win32_Process -Filter "ProcessId=${pid}" -ErrorAction SilentlyContinue).CommandLine`);
}

function stopPid(pid) {
  run("taskkill.exe", ["/PID", String(pid), "/F"], { stdio: "ignore" });
}

function spawnDetached(name, cwd, command, args) {
  const out = fs.openSync(path.join(logs, `${name}.log`), "w");
  const err = fs.openSync(path.join(logs, `${name}.err.log`), "w");
  const child = childProcess.spawn(command, args, {
    cwd,
    detached: true,
    stdio: ["ignore", out, err],
    windowsHide: true,
  });
  child.unref();
  return child.pid;
}

function startCmd(name, cwd, commandLineText) {
  return spawnDetached(name, cwd, "cmd.exe", ["/c", commandLineText]);
}

function ensurePortFree(port, expectedFragment) {
  const current = listener(port);
  if (!current) return;
  const cmd = commandLine(current.OwningProcess);
  const fragments = Array.isArray(expectedFragment) ? expectedFragment : [expectedFragment];
  if (fragments.some((fragment) => cmd.includes(fragment))) {
    console.log(`Port ${port} is already owned by this project.`);
    return;
  }
  if (!stopConflicts) {
    throw new Error(
      `Port ${port} is already in use by PID ${current.OwningProcess}: ${cmd}\nRun: node tools/start_local.js --stop-port-conflicts`,
    );
  }
  console.log(`Stopping conflicting process on port ${port}: PID ${current.OwningProcess}`);
  stopPid(current.OwningProcess);
}

function request(url, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode && res.statusCode >= 200 && res.statusCode < 400);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(timeoutMs, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForReady() {
  for (let i = 0; i < 35; i += 1) {
    const [frontend, backend, qdrant] = await Promise.all([
      request("http://127.0.0.1:3000", 4000),
      request("http://127.0.0.1:8000/health", 4000),
      request("http://127.0.0.1:6333/collections", 4000),
    ]);
    if (frontend && backend && qdrant) return true;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  return false;
}

async function main() {
  console.log("Starting Qdrant...");
  const docker = run("docker", ["compose", "up", "-d", "qdrant"], { stdio: "inherit" });
  if (docker.status !== 0) {
    throw new Error("Docker/Qdrant did not start. Make sure Docker Desktop is running and accessible.");
  }

  ensurePortFree(3000, [path.join("Aiwana", "ai_project", "Rag", "frontend"), "next dev -p 3000"]);
  ensurePortFree(8000, ["uvicorn app.api.main:app", "app.api.main:app --host 127.0.0.1 --port 8000"]);

  if (!listener(8000)) {
    const pid = startCmd("backend-dev", root, ".venv\\Scripts\\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000");
    console.log(`Started backend PID ${pid}`);
  } else {
    console.log("Backend already listening on 8000.");
  }

  if (!listener(3000)) {
    const pid = startCmd("frontend-dev", path.join(root, "frontend"), "npm.cmd run dev");
    console.log(`Started frontend PID ${pid}`);
  } else {
    console.log("Frontend already listening on 3000.");
  }

  if (!(await waitForReady())) {
    throw new Error("Startup timed out. Check logs/backend-dev.err.log and logs/frontend-dev.err.log.");
  }

  console.log("Aiwana is ready:");
  console.log("  Frontend: http://localhost:3000");
  console.log("  Backend:  http://localhost:8000/health");
  console.log("  Qdrant:   http://localhost:6333/dashboard");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
