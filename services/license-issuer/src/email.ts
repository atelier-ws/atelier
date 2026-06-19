/** Deliver a license key by email via Resend (https://resend.com).
 *
 * Resend is the simplest reliable sender from a Worker. To use Cloudflare's
 * own Email Routing `send_email` binding instead, swap this one function -- the
 * caller only needs `sendLicenseEmail`.
 */

export interface SendLicenseEmailOptions {
  apiKey: string;
  from: string;
  to: string;
  token: string;
  plan: string;
  expires: number | null;
}

export async function sendLicenseEmail(
  opts: SendLicenseEmailOptions,
): Promise<void> {
  const expiryText =
    opts.expires === null
      ? "never (lifetime)"
      : new Date(opts.expires * 1000).toISOString().slice(0, 10);
  const text = [
    `Thanks for upgrading to Atelier ${opts.plan}!`,
    "",
    "Activate on any machine with:",
    "",
    `    atelier license activate ${opts.token}`,
    "",
    `Plan:    ${opts.plan}`,
    `Expires: ${expiryText}`,
    "",
    "Check status anytime with:  atelier license status",
    "",
    "Questions? Just reply to this email.",
  ].join("\n");

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${opts.apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: opts.from,
      to: opts.to,
      subject: "Your Atelier Pro license key",
      text,
    }),
  });
  if (!res.ok) {
    throw new Error(`email send failed: ${res.status} ${await res.text()}`);
  }
}
