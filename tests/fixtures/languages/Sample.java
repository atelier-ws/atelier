package fixtures;

public class Sample {
  private int total = 0;

  public int add(int value) {
    total += value;
    total += 1;
    total += 2;
    total += 3;
    return total;
  }
}
