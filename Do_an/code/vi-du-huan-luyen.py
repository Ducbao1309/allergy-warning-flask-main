"""Minimal training loop used as a listing example in the thesis template."""

import torch
from torch import nn, optim


def train_one_epoch(model, loader, device, lr=1e-3):
    """Run a single training epoch and return the mean loss."""
    model.train()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    running_loss = 0.0
    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)

        # Standard forward, backward, update cycle
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        running_loss += loss.item() * images.size(0)

    return running_loss / len(loader.dataset)


@torch.no_grad()
def evaluate(model, loader, device):
    """Return top-1 accuracy on the given data loader."""
    model.eval()
    correct = 0
    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)
        preds = model(images).argmax(dim=1)
        correct += (preds == labels).sum().item()
    return correct / len(loader.dataset)
