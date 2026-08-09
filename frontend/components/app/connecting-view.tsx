'use client';

export const ConnectingView = ({ ref }: React.ComponentProps<'div'>) => {
  return (
    <div ref={ref}>
      <section className="bg-background flex min-h-screen flex-col items-center justify-center text-center">
        <div className="mb-6 flex items-center justify-center">
          <div className="relative flex size-24 animate-pulse items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-indigo-900 text-4xl font-bold text-white">
            अ
          </div>
        </div>

        <h1 className="text-foreground mb-2 text-2xl font-bold">Connecting to ArthSakhi…</h1>

        <p className="text-foreground/70 mb-8 max-w-md text-base leading-6 font-normal">
          Please wait while we prepare your secure voice session
        </p>

        <div className="mb-8 flex justify-center gap-2">
          <div
            className="size-3 animate-bounce rounded-full bg-blue-600"
            style={{ animationDelay: '0ms' }}
          ></div>
          <div
            className="size-3 animate-bounce rounded-full bg-blue-600"
            style={{ animationDelay: '150ms' }}
          ></div>
          <div
            className="size-3 animate-bounce rounded-full bg-blue-600"
            style={{ animationDelay: '300ms' }}
          ></div>
        </div>
      </section>
    </div>
  );
};
