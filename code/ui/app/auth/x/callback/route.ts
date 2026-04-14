import { getXOAuthConfig, getXTokenUrl } from "@/lib/x-oauth";
import { NextRequest, NextResponse } from "next/server";

function toErrorRedirect(request: NextRequest, message: string): NextResponse {
  const url = new URL("/auth/error", request.url);
  url.searchParams.set("error", message);
  return NextResponse.redirect(url);
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const oauthError = searchParams.get("error");

  if (oauthError) {
    return toErrorRedirect(request, `X authorization failed: ${oauthError}`);
  }

  if (!code || !state) {
    return toErrorRedirect(request, "Missing OAuth callback parameters from X.");
  }

  const savedState = request.cookies.get("x_oauth_state")?.value;
  const codeVerifier = request.cookies.get("x_oauth_code_verifier")?.value;

  if (!savedState || !codeVerifier) {
    return toErrorRedirect(
      request,
      "Missing OAuth verifier cookies. Please start sign-in again.",
    );
  }

  if (state !== savedState) {
    return toErrorRedirect(request, "State mismatch detected. Please retry sign-in.");
  }

  const config = getXOAuthConfig();
  const tokenUrl = getXTokenUrl();
  const body = new URLSearchParams({
    code,
    grant_type: "authorization_code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    code_verifier: codeVerifier,
  });

  const headers: HeadersInit = {
    "Content-Type": "application/x-www-form-urlencoded",
  };

  if (config.clientSecret) {
    const credential = Buffer.from(
      `${config.clientId}:${config.clientSecret}`,
      "utf8",
    ).toString("base64");
    headers.Authorization = `Basic ${credential}`;
  }

  const tokenResponse = await fetch(tokenUrl, {
    method: "POST",
    headers,
    body: body.toString(),
    cache: "no-store",
  });

  if (!tokenResponse.ok) {
    const errorText = await tokenResponse.text();
    return toErrorRedirect(
      request,
      `X token exchange failed (${tokenResponse.status}). ${errorText}`,
    );
  }

  const tokenData = (await tokenResponse.json()) as {
    access_token: string;
    expires_in?: number;
    refresh_token?: string;
    scope?: string;
    token_type?: string;
  };

  const successUrl = new URL("/protected", request.url);
  successUrl.searchParams.set("x_auth", "success");
  const response = NextResponse.redirect(successUrl);

  response.cookies.set("x_access_token", tokenData.access_token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: tokenData.expires_in ?? 60 * 60 * 2,
  });

  if (tokenData.refresh_token) {
    response.cookies.set("x_refresh_token", tokenData.refresh_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    });
  }

  response.cookies.set("x_oauth_state", "", { path: "/", maxAge: 0 });
  response.cookies.set("x_oauth_code_verifier", "", { path: "/", maxAge: 0 });

  return response;
}
