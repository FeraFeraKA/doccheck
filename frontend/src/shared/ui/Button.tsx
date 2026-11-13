import type { ButtonHTMLAttributes } from 'react';
import { classes } from '../lib/classes';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost';
}

export function Button({ variant = 'default', className, type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={classes('workspace-button', 'workspace-button-' + variant, className)} {...props} />;
}
