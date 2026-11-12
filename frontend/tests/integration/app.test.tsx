import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it } from 'vitest';
import { App } from '../../src/app/App';

it('показывает стартовую страницу по основному маршруту', () => {
  render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>);
  expect(screen.getByRole('heading', { name: 'DocCheck' })).toBeVisible();
  expect(screen.getByText('Интерфейс проверки документов находится в разработке.')).toBeVisible();
});
