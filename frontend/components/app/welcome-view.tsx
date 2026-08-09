import { Button } from '@/components/ui/button';

function WelcomeImage() {
  return (
    <div className="mb-6 flex items-center justify-center">
      <div className="relative flex size-24 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-indigo-900 text-4xl font-bold text-white">
        अ
      </div>
    </div>
  );
}

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  return (
    <div ref={ref}>
      <section className="bg-background flex min-h-screen flex-col items-center justify-center text-center">
        <WelcomeImage />

        <h1 className="text-foreground mb-1 text-2xl font-bold">ArthSakhi</h1>
        <p className="text-foreground mb-2 text-lg font-medium">अर्थसखी</p>

        <p className="text-foreground/80 mb-6 max-w-md pt-2 text-base leading-6 font-medium">
          Your trusted financial-literacy voice assistant
        </p>

        <p className="text-foreground/70 mb-8 max-w-md text-sm leading-6 font-normal">
          Government schemes and safe digital banking guidance in Hindi, English, and Hinglish.
        </p>

        <Button
          size="lg"
          onClick={onStartCall}
          className="mt-4 rounded-full px-8 text-base font-semibold tracking-wide"
        >
          {startButtonText}
        </Button>

        <div className="mt-12 max-w-md rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="mb-2 text-xs font-semibold text-amber-900">🔒 Safety Reminder</p>
          <p className="text-xs leading-5 text-amber-800">
            Never share your OTP, UPI PIN, password, CVV, or complete account details.
          </p>
        </div>
      </section>

      <div className="fixed bottom-5 left-0 flex w-full items-center justify-center">
        <p className="text-muted-foreground max-w-prose pt-1 text-xs leading-5 font-normal text-pretty md:text-sm">
          Need help? Check out the{' '}
          <a
            target="_blank"
            rel="noopener noreferrer"
            href="https://docs.livekit.io/agents/start/voice-ai/"
            className="underline"
          >
            Voice AI quickstart
          </a>
          .
        </p>
      </div>
    </div>
  );
};
