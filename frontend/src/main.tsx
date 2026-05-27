import React from "react";
import ReactDOM from "react-dom/client";
import { InteractionRequiredAuthError } from "@azure/msal-browser";
import { MsalProvider, useMsal } from "@azure/msal-react";
import App from "./App";
import { AUTH_ENABLED, loginRequest, msalInstance } from "./auth";
import { setAccessTokenProvider, setCachedAccessToken } from "./api";
import "./styles.css";

function AuthenticatedRoot() {
  const { instance, accounts } = useMsal();
  const account = accounts[0] || null;

  React.useEffect(() => {
    if (!AUTH_ENABLED || !account) {
      setAccessTokenProvider(null);
      setCachedAccessToken(null);
      return;
    }

    setAccessTokenProvider(async () => {
      try {
        const response = await instance.acquireTokenSilent({ ...loginRequest, account });
        setCachedAccessToken(response.accessToken);
        return response.accessToken;
      } catch (error) {
        if (error instanceof InteractionRequiredAuthError) {
          await instance.acquireTokenRedirect({ ...loginRequest, account });
        }
        throw error;
      }
    });
  }, [account, instance]);

  if (AUTH_ENABLED && !account) {
    return (
      <main className="login-shell">
        <section className="login-panel">
          <div className="brand-mark login-mark">DAV</div>
          <p className="eyebrow">Car Legalizer</p>
          <h1>Entrar com Microsoft</h1>
          <p>Usa a tua conta Microsoft para aceder aos teus processos DAV guardados na Blob.</p>
          <button className="primary-button" type="button" onClick={() => instance.loginRedirect(loginRequest)}>
            Continuar com Microsoft
          </button>
        </section>
      </main>
    );
  }

  return (
    <App
      authEnabled={AUTH_ENABLED}
      userName={account?.name || account?.username || null}
      onLogout={() => instance.logoutRedirect()}
    />
  );
}

function DevRoot() {
  React.useEffect(() => {
    setAccessTokenProvider(null);
    setCachedAccessToken(null);
  }, []);

  return <App authEnabled={false} userName={null} onLogout={() => undefined} />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {AUTH_ENABLED ? (
      <MsalProvider instance={msalInstance}>
        <AuthenticatedRoot />
      </MsalProvider>
    ) : (
      <DevRoot />
    )}
  </React.StrictMode>,
);
