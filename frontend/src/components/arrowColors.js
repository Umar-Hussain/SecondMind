// Arrow colours for react-chessboard. Arrows are drawn as SVG attributes, which cannot read
// CSS variables, so the Midnight Gold token values are mirrored here (DESIGN.md section 2):
// red = what you played, green = your repertoire / correct move, blue = engine suggestion,
// amber = an opponent move you have not prepared, gold = your own repertoire in Prepare.
export const ARROW = {
  played: "rgba(242,109,109,.9)",     // --error
  good: "rgba(74,222,128,.85)",       // --success
  goodSoft: "rgba(74,222,128,.42)",
  engine: "rgba(106,168,255,.9)",     // --info
  gap: "rgba(245,165,36,.92)",        // --warning
  gold: "rgba(232,176,75,.95)",       // --accent
  punish: "rgba(236,110,190,.95)",    // a distinct colour for "punish their mistake"
};
