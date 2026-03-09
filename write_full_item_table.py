"""Script to write the full_item_table from DK64 to a file."""

from worlds.dk64.archipelago.Items import full_item_table

def write_item_table():
    """Write the full_item_table to a text file."""
    with open("dk64_full_item_table.txt", "w") as f:
        f.write("DK64 Full Item Table\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total items: {len(full_item_table)}\n\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Item Name':<50} {'Item ID':<12} {'Progression':<12}\n")
        f.write("-" * 80 + "\n")
        
        # Sort by item code for better readability
        sorted_items = sorted(full_item_table.items(), key=lambda x: x[1].code if x[1].code else 0)
        
        for item_name, item_data in sorted_items:
            item_id = str(item_data.code) if item_data.code else "None"
            progression = "Yes" if item_data.progression else "No"
            f.write(f"{item_name:<50} {item_id:<12} {progression:<12}\n")
    
    print(f"Successfully wrote {len(full_item_table)} items to dk64_full_item_table.txt")

if __name__ == "__main__":
    write_item_table()
