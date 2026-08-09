'use client';

import { type AgentState } from '@livekit/components-react';

interface StatusIndicatorProps {
  agentState?: AgentState;
  callEnded?: boolean;
  className?: string;
}

export function StatusIndicator({ agentState, callEnded, className = '' }: StatusIndicatorProps) {
  if (callEnded) {
    return (
      <div className={`text-center ${className}`}>
        <div className="mb-4">
          <p className="text-base font-semibold text-red-600">Call ended</p>
        </div>
      </div>
    );
  }

  if (agentState === 'speaking') {
    return (
      <div className={`text-center ${className}`}>
        <div className="mb-4 flex justify-center gap-1">
          <div
            className="h-6 w-1.5 animate-pulse rounded-full bg-gradient-to-t from-blue-500 to-blue-400"
            style={{ animationDuration: '0.6s' }}
          ></div>
          <div
            className="h-8 w-1.5 animate-pulse rounded-full bg-gradient-to-t from-blue-500 to-blue-400"
            style={{ animationDuration: '0.8s', animationDelay: '0.1s' }}
          ></div>
          <div
            className="h-6 w-1.5 animate-pulse rounded-full bg-gradient-to-t from-blue-500 to-blue-400"
            style={{ animationDuration: '0.6s', animationDelay: '0.2s' }}
          ></div>
          <div
            className="h-7 w-1.5 animate-pulse rounded-full bg-gradient-to-t from-blue-500 to-blue-400"
            style={{ animationDuration: '0.7s', animationDelay: '0.3s' }}
          ></div>
        </div>
        <p className="text-base font-semibold text-blue-600">ArthSakhi is speaking</p>
        <p className="mt-1 text-sm text-gray-600">Please wait for the response</p>
      </div>
    );
  }

  if (agentState === 'connected' || agentState === 'ready') {
    return (
      <div className={`text-center ${className}`}>
        <div className="mb-4 flex justify-center">
          <div className="relative h-16 w-16">
            {/* Outer pulsing ring */}
            <div className="absolute inset-0 animate-pulse rounded-full border-2 border-green-400"></div>
            {/* Inner pulsing ring */}
            <div
              className="absolute inset-2 animate-pulse rounded-full border-2 border-green-400"
              style={{ animationDelay: '0.3s' }}
            ></div>
            {/* Center microphone indicator */}
            <div className="absolute inset-4 flex items-center justify-center rounded-full bg-gradient-to-br from-green-400 to-green-600">
              <svg className="h-6 w-6 text-white" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
                <path d="M17 16.91c-1.48 1.46-3.51 2.36-5.7 2.36s-4.22-.9-5.7-2.36M19 12h2a7 7 0 00-7-7v2a5 5 0 015 5z" />
              </svg>
            </div>
          </div>
        </div>
        <p className="text-base font-semibold text-green-600">ArthSakhi is listening</p>
        <p className="mt-1 text-sm text-gray-600">Your turn — speak now</p>
      </div>
    );
  }

  if (agentState === 'thinking') {
    return (
      <div className={`text-center ${className}`}>
        <div className="mb-4 flex justify-center">
          <div className="flex gap-2">
            <div
              className="h-2 w-2 animate-bounce rounded-full bg-blue-500"
              style={{ animationDelay: '0ms' }}
            ></div>
            <div
              className="h-2 w-2 animate-bounce rounded-full bg-blue-500"
              style={{ animationDelay: '150ms' }}
            ></div>
            <div
              className="h-2 w-2 animate-bounce rounded-full bg-blue-500"
              style={{ animationDelay: '300ms' }}
            ></div>
          </div>
        </div>
        <p className="text-base font-semibold text-blue-600">Thinking…</p>
      </div>
    );
  }

  return null;
}
