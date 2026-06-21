/** Deliver a license key by email via SendPulse (https://sendpulse.com).
 *
 * Uses the SendPulse REST API (/smtp/emails) with OAuth2 bearer-token auth.
 * Non-secret config is hardcoded here; only SENDPULSE_API_SECRET is injected.
 * To swap for another sender, replace this one function -- the caller only
 * needs `sendLicenseEmail`.
 */

const SENDPULSE_API_BASE = "https://api.sendpulse.com";
const SMTP_FROM_EMAIL = "noreply@atelier.ws";
const SMTP_FROM_NAME = "Atelier";

export interface SendLicenseEmailOptions {
  apiId: string;
  apiSecret: string;
  to: string;
  token: string;
  plan: string;
  expires: number | null;
}

export async function sendDeviceNotification(
  email: SendEmail,
  to: string,
  deviceName: string,
  action: "added" | "removed",
): Promise<void> {
  const subject = `Atelier device ${action}`;
  const text = [
    `A device was ${action} on your Atelier Pro license.`,
    "",
    `Device: ${deviceName}`,
    "",
    action === "added"
      ? "Atelier allows up to three active devices."
      : "The device slot is now available immediately.",
    "",
    "If this was not you, contact contact@atelier.ws.",
  ].join("\n");
  await email.send({
    to,
    from: { email: "licenses@atelier.ws", name: "Atelier" },
    replyTo: "contact@atelier.ws",
    subject,
    text,
    html: `<p>A device was ${action} on your Atelier Pro license.</p><p><strong>Device:</strong> ${escapeHtml(deviceName)}</p><p>${action === "added" ? "Atelier allows up to three active devices." : "The device slot is now available immediately."}</p><p>If this was not you, contact <a href="mailto:contact@atelier.ws">contact@atelier.ws</a>.</p>`,
  });
}

function escapeHtml(value: string): string {
  const entities: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  };
  return value.replace(
    /[&<>"']/g,
    (character) => entities[character] ?? character,
  );
}

/** Email a one-time, short-lived link to manage devices (SendPulse). */
export async function sendDeviceLoginEmail(opts: {
  apiId: string;
  apiSecret: string;
  to: string;
  url: string;
}): Promise<void> {
  const text = [
    "Manage the devices on your Atelier Pro license using this secure link:",
    "",
    `    ${opts.url}`,
    "",
    "The link expires in 15 minutes and can be used once.",
    "If you did not request this, you can safely ignore this email.",
  ].join("\n");
  const html =
    `<p>Manage the devices on your Atelier Pro license:</p>` +
    `<p><a href="${escapeHtml(opts.url)}">Open the Atelier device manager</a></p>` +
    `<p>The link expires in 15 minutes and can be used once. ` +
    `If you did not request this, you can safely ignore this email.</p>`;
  const token = await getAccessToken(opts.apiId, opts.apiSecret);
  const res = await fetch(`${SENDPULSE_API_BASE}/smtp/emails`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email: {
        html,
        text,
        subject: "Manage your Atelier devices",
        from: { name: SMTP_FROM_NAME, email: SMTP_FROM_EMAIL },
        to: [{ email: opts.to }],
      },
    }),
  });
  if (!res.ok) {
    throw new Error(
      `device login email failed: ${res.status} ${await res.text()}`,
    );
  }
}

/** Fetch a short-lived OAuth2 bearer token from SendPulse. */
async function getAccessToken(
  apiId: string,
  apiSecret: string,
): Promise<string> {
  const res = await fetch(`${SENDPULSE_API_BASE}/oauth/access_token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "client_credentials",
      client_id: apiId,
      client_secret: apiSecret,
    }),
  });
  if (!res.ok) {
    throw new Error(`SendPulse auth failed: ${res.status} ${await res.text()}`);
  }
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
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

  const token = await getAccessToken(opts.apiId, opts.apiSecret);

  const res = await fetch(`${SENDPULSE_API_BASE}/smtp/emails`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email: {
        html: `<pre>${text}</pre>`,
        text,
        subject: "Your Atelier Pro license key",
        from: { name: SMTP_FROM_NAME, email: SMTP_FROM_EMAIL },
        to: [{ email: opts.to }],
      },
    }),
  });
  if (!res.ok) {
    throw new Error(`email send failed: ${res.status} ${await res.text()}`);
  }
}
