import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const helper = fileURLToPath(new URL("./atelier_nudge.py", import.meta.url))

export const AtelierNudge = async () => ({
  "chat.message": async (input, output) => {
    const textParts = output.parts.filter(
      (part) => part.type === "text" && typeof part.text === "string" && !part.synthetic,
    )
    if (textParts.length === 0) return

    const prompt = textParts.map((part) => part.text).join("\n")
    const result = spawnSync("python3", [helper], {
      input: JSON.stringify({
        session_id: input.sessionID,
        prompt,
      }),
      encoding: "utf8",
    })
    if (result.status !== 0 || !result.stdout.trim()) return

    try {
      const nudge = JSON.parse(result.stdout)
      if (typeof nudge.additionalContext !== "string" || !nudge.additionalContext.trim()) return
      textParts[textParts.length - 1].text += `\n\n<atelier-nudge>\n${nudge.additionalContext}\n</atelier-nudge>`
    } catch {
      // Fail open: prompt submission must continue if the helper output is invalid.
    }
  },
})
