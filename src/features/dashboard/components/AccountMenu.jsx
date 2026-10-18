import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"; // adjust path to match your actual shadcn ui folder location
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";
import { LogOut, Moon, Sun } from "lucide-react";
import { useAuth } from "@/features/auth/AuthContext";
import { useState } from "react";
import { toggleTheme } from "@/utils/theme";

export function AccountMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  // Starts from whatever initTheme() applied at load, so the label matches
  // the page instead of always starting at "Dark mode".
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark")
  );

  const userInitials = user?.username ? user.username.slice(0, 2).toUpperCase() : "??";

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  function handleToggleDark() {
    setDark(toggleTheme());
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="secondary"
          size="xs"
          className="grid size-7 place-items-center rounded-full outline outline-offset-[-1px] outline-black/5 transition-opacity hover:opacity-80"
        >
          {userInitials}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
  <div className="px-3 py-2">
    <p className="text-sm font-semibold">{user?.username}</p>
    <p className="text-[11px] text-muted-foreground">{user?.email}</p>
  </div>
  <DropdownMenuSeparator />
  <DropdownMenuItem onSelect={handleToggleDark}>
    {dark ? <Sun className="mr-2 size-3.5" /> : <Moon className="mr-2 size-3.5" />}
    {dark ? "Light mode" : "Dark mode"}
  </DropdownMenuItem>
  <DropdownMenuSeparator />
  <DropdownMenuItem onSelect={handleLogout} className="text-negative focus:text-negative">
    <LogOut className="mr-2 size-3.5" /> Log out
  </DropdownMenuItem>
</DropdownMenuContent>
    </DropdownMenu>
  );
}




