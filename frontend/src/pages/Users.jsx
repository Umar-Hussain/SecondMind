import { useEffect, useState } from "react";
import { api } from "../api.js";
import SearchBox from "../components/SearchBox.jsx";

// Admin only: everyone who has an account, and a way to set a temporary password
// for a user who forgot theirs (tell them to change it on their Profile page).
export default function Users() {
  const [users, setUsers] = useState(null);
  const [query, setQuery] = useState("");
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => { api.get("/admin/users").then(setUsers).catch((e) => setError(e.message)); }, []);

  async function reset(u) {
    const pw = window.prompt(`New temporary password for ${u.username} (at least 8 characters):`);
    if (!pw) return;
    setError(null);
    try {
      await api.post(`/admin/users/${u.id}/password`, { new_password: pw });
      setMsg(`Password for ${u.username} was reset. Ask them to change it on their Profile page.`);
    } catch (e) {
      setError(e.message);
    }
  }

  const q = query.toLowerCase();
  const shown = (users || []).filter((u) => !q || [u.username, u.display_name, u.lichess_username, u.chesscom_username]
    .some((v) => v && v.toLowerCase().includes(q)));

  return (
    <section>
      <div className="page-head">
        <div>
          <h2>Users</h2>
          <p className="muted">{users ? `${users.length} account(s)` : "Loading…"}</p>
        </div>
      </div>
      <SearchBox onSearch={setQuery} placeholder="Search by username or chess account" />
      {msg && <p className="ok">{msg}</p>}
      {error && <div className="alert">{error}</div>}
      <table className="list">
        <thead>
          <tr><th>Username</th><th>Role</th><th>Lichess</th><th>Chess.com</th><th>Repertoires</th><th>Joined</th><th /></tr>
        </thead>
        <tbody>
          {shown.map((u) => (
            <tr key={u.id}>
              <td><b>{u.username}</b>{u.display_name && u.display_name !== u.username && <span className="muted"> · {u.display_name}</span>}</td>
              <td>{u.role === "admin" ? <span className="tag library">admin</span> : "user"}</td>
              <td>{u.lichess_username || "–"}</td>
              <td>{u.chesscom_username || "–"}</td>
              <td>{u.repertoires}</td>
              <td className="muted">{u.created_at ? u.created_at.slice(0, 10) : "–"}</td>
              <td>{u.role !== "admin" && <button className="ghost" onClick={() => reset(u)}>Reset password</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
