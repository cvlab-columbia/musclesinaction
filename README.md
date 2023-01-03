# Muscles in Action

## Environment Configuration

1.) Create a conda environment

2.) 
pip install -e .

3.) 
conda create --name <env> --file requirements.txt

## Downloading & Preparing the Muscles in Action (MIA) Dataset 

## Running Inference with Pretrained Models

1.) To reproduce quantitative results with our Transformer model, use the following command:

python musclesinaction/inference.py

2.) To reproduce quantitative results with our Transformer model, use the following command:

python musclesinaction/viz_test.py

## Training from Scratch

1.) To train the transformer model from scratch, use the following command:

python musclesinaction/train.py

See the train.yaml file in the configs folder to modify hyperparameters.


