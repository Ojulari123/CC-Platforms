# Bundled sample datasets, so a brand-new user's dataset list is never empty.
IRIS_CSV = """sepal_length,sepal_width,petal_length,petal_width,species
5.1,3.5,1.4,0.2,setosa
4.9,3.0,1.4,0.2,setosa
7.0,3.2,4.7,1.4,versicolor
6.4,3.2,4.5,1.5,versicolor
6.3,3.3,6.0,2.5,virginica
5.8,2.7,5.1,1.9,virginica
"""

MONTHLY_SALES_CSV = """month,revenue,units
2025-01,12000,340
2025-02,13500,372
2025-03,11800,318
2025-04,15200,401
2025-05,16750,455
2025-06,14300,389
"""

SAMPLE_DATASETS = [
    ("Iris (sample)", "iris.csv", IRIS_CSV),
    ("Monthly Sales (sample)", "monthly_sales.csv", MONTHLY_SALES_CSV),
]
