public class Calculator {
    
    private int memory;
    
    public Calculator() {
        this.memory = 0;
    }
    
    public int add(int a, int b) {
        return a + b;
    }
    
    public int subtract(int a, int b) {
        return a - b;
    }
    
    public double divide(double numerator, double denominator) {
        if (denominator == 0) {
            throw new ArithmeticException("Division by zero");
        }
        return numerator / denominator;
    }
    
    public void storeInMemory(int value) {
        this.memory = value;
    }
    
    public int getMemory() {
        return memory;
    }
}