/**
 * Login.jsx – Clean sign-in page for ECG Guardian.
 *
 * - Email + password login (backend also accepts username)
 * - Password visibility toggle
 * - Clear validation + server error display
 * - Link to /register for new users
 * - Redirects to / on success
 */
import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Heart, Eye, EyeOff, Loader2, AlertCircle, Shield } from 'lucide-react';
import { loginWithCredentials } from '../services/auth';
import { useApp } from '../context/AppContext';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function Login() {
  const navigate     = useNavigate();
  const { dispatch } = useApp();

  const [identifier, setIdentifier] = useState('');   // email or username
  const [password,   setPassword]   = useState('');
  const [showPw,     setShowPw]     = useState(false);
  const [loading,    setLoading]    = useState(false);
  const [errors,     setErrors]     = useState({});
  const [serverErr,  setServerErr]  = useState('');

  // ── Validation ────────────────────────────────────────
  function validate() {
    const errs = {};
    if (!identifier.trim())
      errs.identifier = 'Please enter your email address.';
    else if (!EMAIL_RE.test(identifier.trim()) && identifier.trim().length < 3)
      errs.identifier = 'Enter a valid email address or username.';
    if (!password)
      errs.password = 'Please enter your password.';
    return errs;
  }

  // ── Submit ────────────────────────────────────────────
  const handleLogin = async (e) => {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) { setErrors(errs); return; }

    setLoading(true);
    setErrors({});
    setServerErr('');

    try {
      const { user } = await loginWithCredentials(identifier.trim(), password);
      dispatch({ type: 'SET_AUTH_USER', payload: user });
      navigate('/', { replace: true });
    } catch (_err) {
      // Generic message — don't reveal whether email exists
      setServerErr('Invalid email or password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // ── Render ────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-slate-50
                    flex items-center justify-center p-4">
      <div className="w-full max-w-md">

        {/* Brand */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-blue-600 flex items-center justify-center
                          mb-3 shadow-lg shadow-blue-200">
            <Heart className="w-7 h-7 text-white" fill="currentColor" />
          </div>
          <h1 className="text-2xl font-bold text-slate-800">ECG Guardian</h1>
          <p className="text-sm text-slate-400 mt-1">AI-Based Remote Cardiac Monitoring</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm">

          {/* Card header */}
          <div className="px-8 pt-7 pb-5 border-b border-slate-100">
            <h2 className="text-lg font-semibold text-slate-800">Welcome back</h2>
            <p className="text-sm text-slate-400 mt-0.5">Sign in to access the monitoring dashboard</p>
          </div>

          {/* Form */}
          <form onSubmit={handleLogin} noValidate className="px-8 py-6 space-y-5">

            {/* Email / username */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Email Address
              </label>
              <input
                type="text"
                value={identifier}
                onChange={e => {
                  setIdentifier(e.target.value);
                  if (errors.identifier) setErrors(v => ({ ...v, identifier: '' }));
                }}
                placeholder="you@example.com"
                autoFocus
                autoComplete="email"
                className={`w-full text-sm px-3 py-2.5 border rounded-xl outline-none transition-all
                  focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400
                  ${errors.identifier ? 'border-red-300 bg-red-50' : 'border-slate-200 bg-white'}`}
              />
              {errors.identifier && (
                <p className="mt-1 text-xs text-red-600 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />{errors.identifier}
                </p>
              )}
            </div>

            {/* Password */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-sm font-medium text-slate-700">Password</label>
                {/* Placeholder — no backend reset flow yet */}
                <span className="text-xs text-slate-400 cursor-default select-none"
                  title="Password reset is not available in this version">
                  Forgot password?
                </span>
              </div>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={e => {
                    setPassword(e.target.value);
                    if (errors.password) setErrors(v => ({ ...v, password: '' }));
                  }}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  className={`w-full text-sm px-3 py-2.5 pr-10 border rounded-xl outline-none
                    transition-all focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400
                    ${errors.password ? 'border-red-300 bg-red-50' : 'border-slate-200 bg-white'}`}
                />
                <button
                  type="button"
                  onClick={() => setShowPw(p => !p)}
                  className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-600 transition-colors"
                  aria-label={showPw ? 'Hide password' : 'Show password'}
                >
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {errors.password && (
                <p className="mt-1 text-xs text-red-600 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />{errors.password}
                </p>
              )}
            </div>

            {/* Server error */}
            {serverErr && (
              <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200
                              rounded-xl text-sm text-red-700">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {serverErr}
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-2.5 text-sm font-semibold
                         bg-blue-600 text-white rounded-xl hover:bg-blue-700 active:scale-[0.98]
                         transition-all disabled:opacity-60 shadow-sm shadow-blue-200 mt-1"
            >
              {loading
                ? <><Loader2 className="w-4 h-4 animate-spin" />Signing in…</>
                : 'Sign In'}
            </button>
          </form>

          {/* Card footer */}
          <div className="px-8 pb-7">
            <p className="text-center text-sm text-slate-500">
              Don&apos;t have an account?{' '}
              <Link to="/register" className="text-blue-600 font-semibold hover:underline">
                Create account
              </Link>
            </p>
          </div>
        </div>

        {/* Security note */}
        <div className="flex items-center justify-center gap-1.5 mt-5 text-xs text-slate-400">
          <Shield className="w-3.5 h-3.5" />
          <span>Your data is encrypted and stored securely</span>
        </div>

      </div>
    </div>
  );
}
