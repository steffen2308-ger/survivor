import tkinter as tk

def main():
    root = tk.Tk()
    root.title("Hello World")

    label = tk.Label(root, text="Hello, World!", font=("Helvetica", 16))
    label.pack(padx=20, pady=20)

    root.mainloop()


if __name__ == "__main__":
    main()
