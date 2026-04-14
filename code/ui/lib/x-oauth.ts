import { createHash, randomBytes } from "crypto";

const X_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize";
const X_TOKEN_URL = "https://api.x.com/2/oauth2/token";
const DEFAULT_SCOPE = "tweet.read users.read offline.access";

export type XOAuthConfig = {
  clientId: string;
  clientSecret?: string;
  redirectUri: string;
  scope: string;
};

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export function getXOAuthConfig(): XOAuthConfig {
  return {
    clientId: requireEnv("X_CLIENT_ID"),
    clientSecret: process.env.X_CLIENT_SECRET,
    redirectUri: requireEnv("X_REDIRECT_URI"),
    scope: process.env.X_OAUTH_SCOPE ?? DEFAULT_SCOPE,
  };
}

export function createCodeVerifier(): string {
  return randomBytes(64).toString("base64url");
}

export function createState(): string {
  return randomBytes(24).toString("base64url");
}

export function createCodeChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

export function buildAuthorizeUrl(params: {
  clientId: string;
  redirectUri: string;
  scope: string;
  state: string;
  codeChallenge: string;
}): string {
  const normalizedScope = params.scope
    .trim()
    .split(/\s+/)
    .map((item) => encodeURIComponent(item))
    .join("%20");
  const query = [
    `response_type=code`,
    `client_id=${encodeURIComponent(params.clientId)}`,
    `redirect_uri=${encodeURIComponent(params.redirectUri)}`,
    `scope=${normalizedScope}`,
    `state=${encodeURIComponent(params.state)}`,
    `code_challenge=${encodeURIComponent(params.codeChallenge)}`,
    `code_challenge_method=S256`,
  ].join("&");

  return `${X_AUTHORIZE_URL}?${query}`;
}

export function getXTokenUrl(): string {
  return X_TOKEN_URL;
}
