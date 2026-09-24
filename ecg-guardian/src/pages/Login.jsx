/**
 * Login.jsx – Email + password sign-in for ECG Guardian.
 * Clean, single-mode login — no OTP tab clutter.
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

  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [showPw,   setShowPw]   = useState(false);
  const [loading,  setLoading]  = useState(false);
  const [errors,   setErrors]   = useState({});
  const [serverErr,setServerErr]= useState('');

  function validate() {
    const errs = {};
    if (!email.trim())
      errs.email = 'Please enter your email address.';
    else if (!EMAIL_RE.test(email.trim()))
      errs.email = 'Enter a valid email address.';
    if (!password)
      errs.password = 'Please enter your password.';
    return errs;
  }

  const handleLogin = async (e) => {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) { setErrors(errs); return; }

    setLoading(true);
    setErrors({});
    setServerErr('');

    try {
      const { user } = await loginWithCredentials(email.trim(), password);
      dispatch({ type: 'SET_AUTH_USER', payload: user });
      navigate('/', { replace: true });
    } catch {
      setServerErr('Invalid email or password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

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

          {/* Header */}
          <div className="px-8 pt-7 pb-5 border-b border-slate-100">
            <h2 className="text-lg font-semibold text-slate-800">Welcome back</h2>
            <p className="text-sm text-slate-400 mt-0.5">Sign in to access the monitoring dashboard</p>
          </div>

          {/* Form */}
          <form onSubmit={handleLogin} noValidate className="px-8 py-6 space-y-5">

            {/* Email */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Email Address
              </label>
              <input
                type="email"
                value={email}
                onChange={e => { setEmail(e.target.value); setErrors(v => ({ ...v, email: '' })); }}
                placeholder="you@example.com"
                autoFocus
                autoComplete="email"
                className={`w-full text-sm px-3 py-2.5 border rounded-xl outline-none transition-all
                  focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400
                  ${errors.email ? 'border-red-300 bg-red-50' : 'border-slate-200 bg-white'}`}
              />
              {errors.email && (
                <p className="mt-1 text-xs text-red-600 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />{errors.email}
                </p>
              )}
            </div>

            {/* Password */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={e => { setPassword(e.target.value); setErrors(v => ({ ...v, password: '' })); }}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  className={`w-full text-sm px-3 py-2.5 pr-10 border rounded-xl outline-none transition-all
                    focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400
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
                         transition-all disabled:opacity-60 shadow-sm shadow-blue-200"
            >
              {loading
                ? <><Loader2 className="w-4 h-4 animate-spin" />Signing in…</>
                : 'Sign In'
              }
            </button>
          </form>

          {/* Footer */}
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
