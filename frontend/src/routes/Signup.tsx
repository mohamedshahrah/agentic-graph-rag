import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { auth } from "../api";
import { Alert, Button, Field, Input } from "../components/ui";
import { AuthLayout } from "./AuthLayout";

const MIN_PASSWORD = 10;

export default function Signup() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await auth.signup(email, password);
      // The response is identical whether or not the address was already
      // registered, so the next step is the same either way.
      navigate("/verify", { state: { email } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Create an account"
      subtitle="We'll email you a code to confirm the address."
      footer={
        <>
          Already have one?{" "}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Email">
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            autoFocus
            required
          />
        </Field>
        <Field
          label="Password"
          hint={`At least ${MIN_PASSWORD} characters.`}
          error={tooShort ? `At least ${MIN_PASSWORD} characters.` : undefined}
        >
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            minLength={MIN_PASSWORD}
            required
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          loading={busy}
          disabled={tooShort}
          className="w-full"
        >
          Continue
        </Button>
      </form>
    </AuthLayout>
  );
}
