/**
 * VerifyEmail – handles the /verify-email?token=... link sent after registration.
 * Calls GET /auth/verify-email?token=... and shows success or failure.
 */
import { useEffect, useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { Heart, CheckCircle, XCircle, Loader2 } from 'lucide-react';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export default function VerifyEmail() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [status,  setStatus]  = useState('loading'); // loading | success | error
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('No verification token found in the URL.');
      return;
    }
    fetch(`${BASE_URL}/auth/verify-email?token=${encodeURIComponent(token)}`)
      .then(r => r.json())
      .then(data => {
        if (data.success) { setStatus('success'); setMessage(data.message || 'Email verified!'); }
        else              { setStatus('error');   setMessage(data.detail  || 'Verification failed.'); }
      })
      .catch(() => {
        setStatus('error');
        setMessage('Could not reach the server. Please try again.');
      });
  }, [token]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-slate-50
                    flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-sm
                      p-10 flex flex-col items-center gap-5 text-center">
        <div className="w-12 h-12 rounded-2xl bg-blue-600 flex items-center justify-center shadow-lg">
          <Heart className="w-6 h-6 text-white" fill="currentColor" />
        </div>
        <h1 className="text-xl font-bold text-slate-800">Email Verification</h1>

        {status === 'loading' && (
          <>
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            <p className="text-sm text-slate-500">Verifying your email…</p>
          </>
        )}
        {status === 'success' && (
          <>
            <CheckCircle className="w-12 h-12 text-emerald-500" />
            <p className="text-sm font-medium text-emerald-700 bg-emerald-50 border border-emerald-200
                          rounded-xl px-4 py-3 w-full">{message}</p>
            <Link to="/login"
              className="w-full flex items-center justify-center py-2.5 text-sm font-semibold
                         bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors">
              Go to Login
            </Link>
          </>
        )}
        {status === 'error' && (
          <>
            <XCircle className="w-12 h-12 text-red-400" />
            <p className="text-sm font-medium text-red-700 bg-red-50 border border-red-200
                          rounded-xl px-4 py-3 w-full">{message}</p>
            <Link to="/login"
              className="w-full flex items-center justify-center py-2.5 text-sm font-semibold
                         bg-slate-600 text-white rounded-xl hover:bg-slate-700 transition-colors">
              Return to Login
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
