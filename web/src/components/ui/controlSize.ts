/** The height scale every control in the app is built from.
 *
 *  Its own module rather than an export from Button, so that anything which
 *  has to stand beside a button — InstallCommand on the landing page — can
 *  share the exact height without importing a component to get at a constant.
 */
export type Size = 'sm' | 'md' | 'lg' | 'xl';

export const CONTROL_HEIGHT: Record<Size, string> = {
  sm: 'h-7',
  md: 'h-8',
  lg: 'h-9',
  // The landing page's single call to action. The dashboard's densest control
  // and a marketing page's one button are not the same object, and 44px is the
  // height at which a thumb stops missing it.
  xl: 'h-11',
};
