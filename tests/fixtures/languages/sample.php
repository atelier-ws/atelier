<?php
namespace Fixtures;

class SampleService {
    public function add(int $value): int {
        $total = $value;
        $total += 1;
        $total += 2;
        $total += 3;
        return $total;
    }
}

function helper(int $value): int {
    return $value + 1;
}
