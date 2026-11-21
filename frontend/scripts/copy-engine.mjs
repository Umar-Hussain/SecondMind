// Copies the Stockfish WebAssembly build from node_modules into public/ so Vite
// serves it as a static Web Worker. Runs automatically before `dev` and `build`.
// Stockfish is GPL-3.0: https://github.com/official-stockfish/Stockfish
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "stockfish", "bin");
const dest = join(root, "public", "stockfish");
mkdirSync(dest, { recursive: true });
for (const f of ["stockfish-19-lite-single.js", "stockfish-19-lite-single.wasm"]) {
  copyFileSync(join(src, f), join(dest, f));
}
console.log("Stockfish WASM copied to public/stockfish/");
