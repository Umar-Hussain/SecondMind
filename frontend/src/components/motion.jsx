import { useEffect, useRef, useState } from "react";

// Small motion helpers for the Midnight Gold design (DESIGN.md section 7, tier L2).
// Only opacity/transform animate; everything respects prefers-reduced-motion and the
// pointer effects run only on devices that can hover.

const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const canHover = () => typeof window !== "undefined" && window.matchMedia("(hover: hover) and (pointer: fine)").matches;

// Adds .in to every .reveal inside the container once it is 15% visible (once only).
export function useReveal(ref) {
  useEffect(() => {
    const root = ref.current;
    if (!root) return undefined;
    const els = root.querySelectorAll(".reveal");
    if (reduced() || !("IntersectionObserver" in window)) {
      els.forEach((el) => el.classList.add("in"));
      return undefined;
    }
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { threshold: 0.15 });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [ref]);
}

// True once the page has scrolled past `offset` px (nav gets its "scrolled" look).
export function useScrolled(offset = 8) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > offset);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, [offset]);
  return scrolled;
}

// A button that leans toward the pointer by up to `strength` px (rAF-throttled).
export function Magnetic({ children, strength = 6, className = "", ...props }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || reduced() || !canHover()) return undefined;
    let raf = 0;
    const move = (e) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const r = el.getBoundingClientRect();
        const x = ((e.clientX - r.left) / r.width - 0.5) * 2 * strength;
        const y = ((e.clientY - r.top) / r.height - 0.5) * 2 * strength;
        el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
      });
    };
    const leave = () => { cancelAnimationFrame(raf); el.style.transform = ""; };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => { cancelAnimationFrame(raf); el.removeEventListener("pointermove", move); el.removeEventListener("pointerleave", leave); };
  }, [strength]);
  return <button ref={ref} className={`magnetic ${className}`} {...props}>{children}</button>;
}

// Heading whose words rise one after another when it scrolls into view.
export function RevealWords({ as: Tag = "h2", text, className = "" }) {
  const ref = useRef(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (reduced() || !("IntersectionObserver" in window)) { setInView(true); return undefined; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setInView(true); io.disconnect(); } }, { threshold: 0.4 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <Tag ref={ref} className={`reveal-words ${inView ? "in" : ""} ${className}`} aria-label={text}>
      {text.split(" ").map((w, i) => (
        <span key={i} className="rw" aria-hidden="true" style={{ transitionDelay: `${i * 40}ms` }}>{w}&nbsp;</span>
      ))}
    </Tag>
  );
}

// Types `text` once, character by character, with a blinking caret.
export function TypeText({ text, speed = 38, startDelay = 300, className = "" }) {
  const [n, setN] = useState(reduced() ? text.length : 0);
  useEffect(() => {
    if (reduced()) return undefined;
    let i = 0;
    let t;
    const start = setTimeout(function tick() {
      i += 1;
      setN(i);
      if (i < text.length) t = setTimeout(tick, speed);
    }, startDelay);
    return () => { clearTimeout(start); clearTimeout(t); };
  }, [text, speed, startDelay]);
  return (
    <span className={`type-text ${className}`} aria-label={text}>
      <span aria-hidden="true">{text.slice(0, n)}</span>
      <span className={`caret ${n >= text.length ? "done" : ""}`} aria-hidden="true" />
    </span>
  );
}

// Feeds the pointer position into --mx/--my of each .spotlight card inside the container.
export function useSpotlight(ref) {
  useEffect(() => {
    const root = ref.current;
    if (!root || !canHover()) return undefined;
    let raf = 0;
    const move = (e) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        root.querySelectorAll(".spotlight").forEach((card) => {
          const r = card.getBoundingClientRect();
          card.style.setProperty("--mx", `${e.clientX - r.left}px`);
          card.style.setProperty("--my", `${e.clientY - r.top}px`);
        });
      });
    };
    root.addEventListener("pointermove", move);
    return () => { cancelAnimationFrame(raf); root.removeEventListener("pointermove", move); };
  }, [ref]);
}
