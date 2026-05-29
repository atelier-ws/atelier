use std::fmt::Display;

pub struct SampleService {
    name: String,
}

impl SampleService {
    pub fn run<T: Display>(&self, value: T) -> String {
        let mut total = 0;
        total += self.name.len();
        total += 1;
        total += 2;
        total += 3;
        format!("{}:{value}:{total}", self.name)
    }
}

pub fn helper(value: i32) -> i32 {
    value + 1
}
