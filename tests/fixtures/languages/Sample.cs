using System;

namespace Fixtures {
  public class SampleService {
    private int total = 0;

    public int Add(int value) {
      total += value;
      total += 1;
      total += 2;
      total += 3;
      return total;
    }
  }
}
