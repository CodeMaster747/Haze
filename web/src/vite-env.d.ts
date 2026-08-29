/// <reference types="vite/client" />

/** True in the Firebase-hosted demo build; false in the agent-served build.
 *  Injected by vite.config.ts `define` so it is dead-code-eliminated. */
declare const __HAZE_DEMO__: boolean;
