import type { ButtonHTMLAttributes, Ref } from 'react';
import { classes } from '../lib/classes';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  ref?: Ref<HTMLButtonElement>;
  variant?: 'default' | 'outline' | 'ghost';
}

export function Button({ variant = 'default', className, type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={classes('workspace-button', 'workspace-button-' + variant, className)} {...props} />;
}
