import { PublicClientApplication, type Configuration } from "@azure/msal-browser";

export const AUTH_ENABLED = Boolean(import.meta.env.VITE_AUTH_CLIENT_ID);

export const API_SCOPE =
  (import.meta.env.VITE_API_SCOPE as string | undefined) ||
  (import.meta.env.VITE_AUTH_CLIENT_ID ? `api://${import.meta.env.VITE_AUTH_CLIENT_ID}/access_as_user` : "");

export const msalConfig: Configuration = {
  auth: {
    clientId: (import.meta.env.VITE_AUTH_CLIENT_ID as string | undefined) || "dev-disabled",
    authority: (import.meta.env.VITE_AUTH_AUTHORITY as string | undefined) || "https://login.microsoftonline.com/common",
    redirectUri: (import.meta.env.VITE_AUTH_REDIRECT_URI as string | undefined) || window.location.origin,
  },
  cache: {
    cacheLocation: "localStorage",
  },
};

export const loginRequest = {
  scopes: API_SCOPE ? [API_SCOPE] : [],
};

export const msalInstance = new PublicClientApplication(msalConfig);
