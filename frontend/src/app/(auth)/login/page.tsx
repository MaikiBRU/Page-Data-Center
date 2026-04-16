import LoginClient from "./LoginClient";

export default function LoginPage() {
  const initialClientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
  return <LoginClient initialClientId={initialClientId} />;
}
