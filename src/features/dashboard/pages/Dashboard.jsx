import { Outlet } from "react-router-dom";

import TopBar from "@/features/dashboard/components/TopBar";
import SiteFooter from "@/features/dashboard/components/SiteFooter";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import AssistantPanel from "@/features/assistant/components/AssistantPanel";
import { useAssistant } from "@/features/assistant/AssistantContext";

const Dashboard = () => {
  const { isOpen, setIsOpen } = useAssistant();

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <TopBar onOpenAssistant={() => setIsOpen(true)} />
      <div className="flex-1">
        <Outlet />
      </div>
      <SiteFooter />

      <Sheet open={isOpen} onOpenChange={setIsOpen}>
        <SheetContent side="right" showCloseButton={false} className="w-full p-0 sm:max-w-[440px]">
          <AssistantPanel />
        </SheetContent>
      </Sheet>
    </div>
  );
};

export default Dashboard;





