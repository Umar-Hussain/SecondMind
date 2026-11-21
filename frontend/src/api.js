// Fetch wrapper around the FastAPI backend (served at /api in production, proxied by Vite in dev).
// The login token lives in localStorage and is sent as a Bearer header on every call.

const BASE = "/api";
const TOKEN_KEY = "secondmind.token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // storage disabled: the user simply has to log in again
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

async function request(path, options = {}) {
  const token = getToken();
  const res = await fetch(BASE + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // Not JSON: a proxy or crash page (e.g. "Internal Server Error"). Show something readable.
    if (!res.ok) throw new Error(`Server error (${res.status}). Please try again in a moment.`);
    throw new Error("The server sent an unexpected reply.");
  }
  if (res.status === 401 && token) {
    setToken(null);
    window.dispatchEvent(new Event("secondmind:logout")); // session expired
  }
  if (!res.ok) {
    const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText;
    throw new Error(detail);
  }
  return data;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: (path, body) => request(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: (path) => request(path, { method: "DELETE" }),
};

// WebSocket URL for server-side live analysis (fallback when the browser engine is unavailable).
export function analysisSocketUrl() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${BASE}/ws/analysis`;
}

// Normalized position key, identical to the backend's fen_key (first four FEN fields).
export function fenKey(fen) {
  return fen.split(" ").slice(0, 4).join(" ");
}
