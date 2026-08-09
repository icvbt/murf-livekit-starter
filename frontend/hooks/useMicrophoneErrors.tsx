import { useEffect, useState } from 'react';
import { Track } from 'livekit-client';
import { toast as sonnerToast } from 'sonner';
import { WarningIcon } from '@phosphor-icons/react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

export function useMicrophoneErrors(
  onDeviceError?: (error: { source: Track.Source; error: Error }) => void
) {
  const [microphoneError, setMicrophoneError] = useState<Error | null>(null);

  const handleDeviceError = (error: { source: Track.Source; error: Error }) => {
    if (error.source === Track.Source.Microphone) {
      const errorMessage = error.error?.message || 'Unknown microphone error';

      // Check if it's a permission denied error
      if (
        errorMessage.includes('NotAllowedError') ||
        errorMessage.includes('Permission denied') ||
        errorMessage.includes('permission')
      ) {
        setMicrophoneError(error.error);

        sonnerToast.custom(
          (id) => (
            <Alert
              onClick={() => sonnerToast.dismiss(id)}
              className="w-full border border-red-200 bg-red-50 md:w-[400px]"
            >
              <WarningIcon weight="bold" className="text-red-600" />
              <AlertTitle className="text-red-900">Microphone access blocked</AlertTitle>
              <AlertDescription className="mt-2 space-y-3 text-sm text-red-800">
                <div>
                  <p className="mb-1 font-semibold">English:</p>
                  <p>Allow microphone permission in your browser settings, then try again.</p>
                </div>
                <div>
                  <p className="mb-1 font-semibold">Hindi:</p>
                  <p>
                    अपने ब्राउज़र की साइट सेटिंग्स में माइक्रोफ़ोन की अनुमति दें और फिर दोबारा
                    प्रयास करें।
                  </p>
                </div>
                <button
                  onClick={() => {
                    sonnerToast.dismiss(id);
                    setMicrophoneError(null);
                    window.location.reload();
                  }}
                  className="mt-3 rounded bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
                >
                  Try again
                </button>
              </AlertDescription>
            </Alert>
          ),
          { duration: 15_000 }
        );
      }
    }

    // Call the original handler if provided
    onDeviceError?.(error);
  };

  return { handleDeviceError, microphoneError };
}
