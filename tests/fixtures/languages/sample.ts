export interface Item {
  id: string;
  total: number;
}

export class Cart {
  private items: Item[] = [];

  add(item: Item): number {
    this.items.push(item);
    const subtotal = this.items.reduce((sum, current) => sum + current.total, 0);
    return subtotal;
  }
}

export function checkout(cart: Cart): number {
  return cart.add({ id: "sample", total: 42 });
}
