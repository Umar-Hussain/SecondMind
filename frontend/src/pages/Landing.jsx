import { useEffect, useState } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";
import Brand from "../components/Brand.jsx";

// Public landing page: hero with a board that plays through an opening, two calls to
// action, and four feature cards. Shown to visitors who are not logged in.

// The hero board plays this line on a loop; the green arrow previews the next move.
const LINE = ["e2e4", "c7c6", "d2d4", "d7d5", "e4e5", "c8f5", "g1f3", "e7e6", "f1e2", "c6c5"];

const FEATURES = [
  { icon: "⌖", title: "Find your leaks", text: "See exactly where you leave your own repertoire, ranked by how many games it cost you." },
  { icon: "♞", title: "Prepare for anyone", text: "Type an opponent's Lichess or Chess.com name and see their moves on the board, with the best replies as arrows." },
  { icon: "↻", title: "Train what matters", text: "Quizzes built from your own mistakes, repeated just before you would forget them." },
  { icon: "✓", title: "Explanations you can trust", text: "Every move is checked by Stockfish, and the AI may only quote moves and sources our tools have verified." },
];

const STEPS = [
  ["Import", "Upload a PGN or Lichess study, or copy a ready-made repertoire."],
  ["Connect", "Add your Lichess or Chess.com name. No password needed."],
  ["Improve", "Fix the leaks, prepare for opponents, and train."],
];

function HeroBoard() {
  const [ply, setPly] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setPly((p) => (p >= LINE.length ? 0 : p + 1)), 1400);
    return () => clearInterval(t);
  }, []);
  const game = new Chess();
  LINE.slice(0, ply).forEach((u) => game.move({ from: u.slice(0, 2), to: u.slice(2, 4) }));
  const next = LINE[ply];
  const [size, setSize] = useState(360);
  useEffect(() => {
    const fit = () => setSize(Math.max(240, Math.min(380, window.innerWidth - 48)));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  return (
    <div className="hero-board" aria-hidden="true">
      <Chessboard position={game.fen()} boardWidth={size} arePiecesDraggable={false} animationDuration={350}
        customArrows={next ? [[next.slice(0, 2), next.slice(2, 4), "rgba(21,120,27,.85)"]] : []}
        customLightSquareStyle={{ backgroundColor: "#f0d9b5" }} customDarkSquareStyle={{ backgroundColor: "#b58863" }}
        customBoardStyle={{ borderRadius: "6px" }} />
    </div>
  );
}

export default function Landing({ onAuth }) {
  return (
    <div className="landing">
      <header className="land-nav">
        <Brand size={30} />
        <nav>
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
        </nav>
        <div className="land-actions">
          <button className="outline" onClick={() => onAuth("login")}>Sign in</button>
          <button className="primary" onClick={() => onAuth("signup")}>Sign up</button>
        </div>
      </header>

      <section className="hero">
        <HeroBoard />
        <div className="hero-copy">
          <h1>Second<b>Mind</b></h1>
          <p className="hero-tag">Your personal opening second.</p>
          <p className="hero-sub">
            Import your repertoire, connect your games, and see where you go wrong, why, and what to play instead.
            Then prepare for your next opponent.
          </p>
          <div className="hero-cta">
            <button className="primary big" onClick={() => onAuth("signup")}>Get started free</button>
            <a className="ghost-link big" href="#features">See what it does</a>
          </div>
        </div>
      </section>

      <section className="features" id="features">
        <h2>Everything a second does, for every player</h2>
        <div className="feature-grid">
          {FEATURES.map((f) => (
            <article key={f.title} className="feature">
              <span className="feature-icon" aria-hidden="true">{f.icon}</span>
              <h3>{f.title}</h3>
              <p>{f.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="how" id="how">
        <h2>How it works</h2>
        <ol className="steps">
          {STEPS.map(([t, d], i) => (
            <li key={t}><span className="step-num">{i + 1}</span><div><h3>{t}</h3><p>{d}</p></div></li>
          ))}
        </ol>
        <button className="primary big" onClick={() => onAuth("signup")}>Create your free account</button>
      </section>

      <footer className="land-foot">
        <Brand size={20} />
        <span>Free and open to every player.</span>
      </footer>
    </div>
  );
}
