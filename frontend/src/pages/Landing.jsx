import { useEffect, useRef, useState } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";
import Brand from "../components/Brand.jsx";
import { ARROW } from "../components/arrowColors.js";
import { Magnetic, RevealWords, TypeText, useReveal, useScrolled, useSpotlight } from "../components/motion.jsx";

// Public landing page in the Midnight Gold design (DESIGN.md). Signature moments:
//   hero      : aurora background, gold gradient "Mind", typed tagline, magnetic CTA,
//               a board playing an opening with live "you vs repertoire" cards;
//   hook      : an endless band of opening names right after the hero;
//   features  : an uneven bento grid whose cards follow the pointer with a gold spotlight;
//   headings  : words rise in sequence on scroll;  detail: the logo knight hops on hover.

// The hero board plays this Caro-Kann line on a loop; the green arrow previews the next move.
const LINE = ["e2e4", "c7c6", "d2d4", "d7d5", "e4e5", "c8f5", "g1f3", "e7e6", "f1e2", "c6c5"];
const OPENINGS = ["Caro-Kann", "Sicilian Najdorf", "Ruy Lopez", "Queen's Gambit", "King's Indian", "Italian Game",
  "French Defence", "London System", "Scandinavian", "Nimzo-Indian", "English Opening", "Evans Gambit"];

const STEPS = [
  ["Import your repertoire", "Upload a PGN or Lichess study, or start from a ready-made repertoire in the library."],
  ["Connect your games", "Add your Lichess or Chess.com name. It runs in the background. No password, ever."],
  ["Fix what costs you", "See your move next to your repertoire, practise the lines, and train your weak spots."],
];

// Inline icons (lucide-style strokes) so no icon font or emoji is needed.
const ICON = {
  target: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.2" /></>,
  scope: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /><path d="M11 8v6M8 11h6" /></>,
  play: <><path d="M6 4l14 8-14 8z" /></>,
  repeat: <><path d="M17 2l4 4-4 4" /><path d="M3 11V9a3 3 0 0 1 3-3h15" /><path d="M7 22l-4-4 4-4" /><path d="M21 13v2a3 3 0 0 1-3 3H3" /></>,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="m9 12 2 2 4-4" /></>,
  arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
};
function Icon({ name, size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICON[name]}</svg>
  );
}

function useBoardSize(max) {
  const [size, setSize] = useState(max);
  useEffect(() => {
    const fit = () => setSize(Math.max(240, Math.min(max, window.innerWidth - 56)));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [max]);
  return size;
}

function HeroBoard() {
  const [ply, setPly] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setPly((p) => (p >= LINE.length ? 0 : p + 1)), 1500);
    return () => clearInterval(t);
  }, []);
  const game = new Chess();
  LINE.slice(0, ply).forEach((u) => game.move({ from: u.slice(0, 2), to: u.slice(2, 4) }));
  const next = LINE[ply];
  const size = useBoardSize(420);
  return (
    <div className="hero-visual" aria-hidden="true">
      <div className="hero-board">
        <Chessboard position={game.fen()} boardWidth={size} arePiecesDraggable={false} animationDuration={380}
          customArrows={next ? [[next.slice(0, 2), next.slice(2, 4), ARROW.good]] : []}
          customLightSquareStyle={{ backgroundColor: "var(--board-light)" }}
          customDarkSquareStyle={{ backgroundColor: "var(--board-dark)" }}
          customBoardStyle={{ borderRadius: "8px" }} />
      </div>
      <div className="float-card fc-1">
        <span className="fc-label">You played</span>
        <span className="fc-move">5.Bd3 <span className="mq mq-inaccuracy"><span className="mq-sym">?!</span></span></span>
      </div>
      <div className="float-card fc-2">
        <span className="fc-label">Your repertoire</span>
        <span className="fc-move">5.Nf3 <span className="mq mq-book"><span className="mq-sym">📖</span></span></span>
      </div>
      <div className="float-card fc-3">
        <span className="fc-dot" /> Stockfish agrees · +0.4
      </div>
    </div>
  );
}

export default function Landing({ onAuth }) {
  const page = useRef(null);
  const bento = useRef(null);
  const scrolled = useScrolled();
  useReveal(page);
  useSpotlight(bento);

  return (
    <div className="landing" ref={page}>
      <header className={`land-nav ${scrolled ? "scrolled" : ""}`}>
        <Brand size={30} />
        <nav aria-label="Sections">
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
        </nav>
        <div className="land-actions">
          <button className="ghost" onClick={() => onAuth("login")}>Sign in</button>
          <button className="primary" onClick={() => onAuth("signup")}>Get started</button>
        </div>
      </header>

      {/* ---------- hero ---------- */}
      <section className="hero">
        <div className="aurora" aria-hidden="true"><span className="a1" /><span className="a2" /><span className="a3" /></div>
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow"><TypeText text="Your personal opening second" /></p>
            <h1 className="hero-title">Second<span className="gold-text">Mind</span></h1>
            <p className="hero-lead">
              Stop losing to the same opening mistakes. SecondMind reads your games, shows the exact move where you left
              your repertoire, and trains you until it sticks.
            </p>
            <div className="hero-cta">
              <Magnetic className="primary big" onClick={() => onAuth("signup")}>
                Get started free <Icon name="arrow" size={18} />
              </Magnetic>
              <a className="btn-outline big" href="#how">See how it works</a>
            </div>
            <ul className="trust">
              <li><Icon name="shield" size={16} /> Every move checked by Stockfish</li>
              <li><Icon name="target" size={16} /> Lichess + Chess.com</li>
              <li><Icon name="repeat" size={16} /> Free for every player</li>
            </ul>
          </div>
          <HeroBoard />
        </div>
      </section>

      {/* ---------- hook: endless band of openings ---------- */}
      <div className="marquee" aria-hidden="true">
        <div className="marquee-track">
          {[...OPENINGS, ...OPENINGS].map((o, i) => <span key={i}>{o}<i>◆</i></span>)}
        </div>
      </div>

      {/* ---------- features: spotlight bento ---------- */}
      <section className="section" id="features">
        <div className="container">
          <p className="eyebrow reveal">What it does</p>
          <RevealWords text="Everything a second does, for every player" className="section-title" />
          <div className="bento" ref={bento}>
            <article className="spotlight bento-card b-wide reveal">
              <span className="bc-icon"><Icon name="target" /></span>
              <h3>Find your leaks</h3>
              <p>See every opening you actually play, and the exact move where each game left your repertoire, ranked by how many games it cost you.</p>
              <div className="bc-demo">
                <div className="bc-row"><span>Italian Game</span><span className="tag bad">4 to fix</span></div>
                <div className="bc-row"><span>Caro-Kann Defence</span><span className="tag warn">1 gap</span></div>
                <div className="bc-row"><span>Ruy Lopez</span><span className="tag good">on track</span></div>
              </div>
            </article>
            <article className="spotlight bento-card reveal" data-delay="1">
              <span className="bc-icon"><Icon name="play" /></span>
              <h3>Practise your lines</h3>
              <p>The app plays your opponent's moves. You answer with yours, with hints when you need them.</p>
            </article>
            <article className="spotlight bento-card reveal">
              <span className="bc-icon"><Icon name="scope" /></span>
              <h3>Prepare for anyone</h3>
              <p>Type your next opponent's name. See what they play and how to beat it, as arrows on the board.</p>
            </article>
            <article className="spotlight bento-card reveal" data-delay="1">
              <span className="bc-icon"><Icon name="repeat" /></span>
              <h3>Train what matters</h3>
              <p>Quizzes from your own mistakes, repeated just before you would forget them.</p>
            </article>
            <article className="spotlight bento-card reveal" data-delay="2">
              <span className="bc-icon"><Icon name="shield" /></span>
              <h3>Answers you can trust</h3>
              <p>Every move is checked by Stockfish. The AI may only quote moves and sources our tools verified.</p>
              <div className="bc-badges">
                <span className="mq mq-brilliant"><span className="mq-sym">!!</span></span>
                <span className="mq mq-best"><span className="mq-sym">★</span></span>
                <span className="mq mq-book"><span className="mq-sym">📖</span></span>
                <span className="mq mq-inaccuracy"><span className="mq-sym">?!</span></span>
                <span className="mq mq-blunder"><span className="mq-sym">??</span></span>
              </div>
            </article>
          </div>
        </div>
      </section>

      {/* ---------- how it works ---------- */}
      <section className="section section-alt" id="how">
        <div className="container">
          <p className="eyebrow reveal">How it works</p>
          <RevealWords text="Three steps to a repertoire you trust" className="section-title" />
          <ol className="steps">
            {STEPS.map(([t, d], i) => (
              <li key={t} className="step reveal" data-delay={i}>
                <span className="step-num">{i + 1}</span>
                <h3>{t}</h3>
                <p>{d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ---------- closing call to action ---------- */}
      <section className="section">
        <div className="container">
          <div className="cta-band reveal">
            <h2>Your next game starts in the opening.</h2>
            <p>Make sure you know what comes after move five.</p>
            <Magnetic className="primary big" onClick={() => onAuth("signup")}>Create your free account <Icon name="arrow" size={18} /></Magnetic>
          </div>
        </div>
      </section>

      <footer className="land-foot">
        <Brand size={22} />
        <span>Free and open to every player. Every move checked by Stockfish.</span>
        <span className="foot-note">Hover the knight. It knows one move.</span>
      </footer>
    </div>
  );
}
