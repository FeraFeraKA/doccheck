import { describe, expect, it } from 'vitest';
import { classes } from '../../src/shared/lib/classes';

describe('classes', () => {
  it('объединяет условные классы и разрешает конфликт Tailwind в пользу последнего', () => {
    expect(classes('p-2', { hidden: false }, 'p-4')).toBe('p-4');
  });
});
