export class Cart {
  constructor() {
    this.items = [];
  }

  add(item) {
    this.items.push(item);
    const subtotal = this.items.reduce((sum, current) => sum + current.total, 0);
    return subtotal;
  }
}

export function checkout(cart) {
  return cart.add({ id: "sample", total: 42 });
}
