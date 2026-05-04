import { spawnSync } from "node:child_process";

const forwarded = process.argv
    .slice(2)
    .filter((arg) => arg !== "--watchAll=false" && arg !== "--watchAll" && arg !== "false");

const args = ["vitest", "run", ...forwarded];
const result = spawnSync("npx", args, { stdio: "inherit" });
process.exit(result.status ?? 1);
